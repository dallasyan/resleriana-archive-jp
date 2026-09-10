import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

import frida


HOOKS = {
    0x5776250: (1,),
    0x57762C0: (1,),
    0x66A4630: (1,),
    0x85D9070: (1,),  # AesManaged.set_IV
    0x85D90D0: (1,),  # AesManaged.set_Key
    0x85D92C0: (1, 2),  # AesManaged.CreateDecryptor(key, iv)
    0x85D9AB0: (1,),  # AesCryptoServiceProvider.set_IV
    0x85D9AC0: (1,),  # AesCryptoServiceProvider.set_Key
    0x85D9890: (1, 2),  # AesCryptoServiceProvider.CreateDecryptor(key, iv)
}


def default_game_root() -> pathlib.Path:
    candidates = []
    configured_root = pathlib.Path(os.environ["JAPANESE_GAME_DIR"]) if os.environ.get("JAPANESE_GAME_DIR") else None
    if configured_root is not None:
        candidates.append(configured_root)
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    candidates.extend((pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent))
    for candidate in candidates:
        if (candidate / "AtelierResleriana.exe").is_file() or (candidate / "japanese-capture").is_dir():
            return candidate
    return candidates[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", default="AtelierResleriana.exe")
    parser.add_argument("--output", help="observer output directory; defaults under the Windows temporary directory")
    parser.add_argument("--game-root", default=str(default_game_root()), help="Japanese game directory")
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--keep-waiting", action="store_true", help="keep observing across temporary game-process gaps")
    parser.add_argument("--stop-file", help="stop after the launcher signals that the game has exited")
    args = parser.parse_args()
    keep_waiting = args.keep_waiting or os.environ.get("JAPANESE_OFFLINE") == "1"
    print(f"Observer keep-waiting: {keep_waiting}", flush=True)

    game_root = pathlib.Path(args.game_root)
    base_output = pathlib.Path(args.output) if args.output else game_root / "japanese-capture" / f"native-observer-{time.strftime('%Y%m%d-%H%M%S')}"
    output = base_output
    suffix = 1
    while output.exists():
        output = base_output.with_name(f"{base_output.name}-{suffix}")
        suffix += 1

    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        if args.output:
            raise
        base_output = pathlib.Path(tempfile.gettempdir()) / "AtelierResleriana" / base_output.name
        output = base_output
        suffix = 1
        while output.exists():
            output = base_output.with_name(f"{base_output.name}-{suffix}")
            suffix += 1
        output.mkdir(parents=True, exist_ok=False)
    print(f"Observer output: {output}", flush=True)
    material_path = output / "aes-material.json"
    material = {
        "key": None,
        "iv": None,
        "key_candidates": [],
        "iv_candidates": [],
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    def save_material(path):
        try:
            temporary_path = path.with_name(path.name + ".tmp")
            temporary_path.write_text(json.dumps(material, indent=2), encoding="utf-8")
            temporary_path.replace(path)
        except OSError as error:
            print(f"Could not save AES material to {path}: {error}", flush=True)

    def persist_root_material_if_missing():
        root_material_path = game_root / "aes-material.json"
        if not material["key"] or not material["iv"] or root_material_path.exists():
            return
        save_material(root_material_path)

    device = frida.get_local_device()
    process = None
    deadline = time.monotonic() + args.seconds
    while process is None and time.monotonic() < deadline:
        for candidate in device.enumerate_processes():
            if candidate.name.lower() == args.process.lower():
                process = candidate
                break
        if process is None:
            time.sleep(0.25)
    if process is None:
        print(f"Did not find {args.process} within {args.seconds:g} seconds.", flush=True)
        return

    source = f"""
    const hooks = {json.dumps([{'rva': rva, 'args': list(indices)} for rva, indices in HOOKS.items()])};
    let sequence = 0;

    function installHooks() {{
        const module = Process.findModuleByName('GameAssembly.dll');
        if (module === null) {{
            setTimeout(installHooks, 100);
            return;
        }}

        for (const hook of hooks) {{
            Interceptor.attach(module.base.add(hook.rva), {{
                onEnter(args) {{
                    for (const argIndex of hook.args) {{
                        try {{
                            send({{ pid: Process.id, hit: '0x' + hook.rva.toString(16), arg: argIndex }});
                            const array = args[argIndex];
                            if (array.isNull()) continue;
                            const length = array.add(0x18).readU64().toNumber();
                            if (length <= 0 || length > 50 * 1024 * 1024) continue;
                            const data = array.add(0x20).readByteArray(length);
                            send({{ pid: Process.id, rva: '0x' + hook.rva.toString(16), arg: argIndex, length: length, sequence: sequence++ }}, data);
                        }} catch (error) {{
                            send({{ pid: Process.id, error: error.toString() }});
                        }}
                    }}
                }}
            }});
        }}
        send({{ ready: true, pid: Process.id, module: module.base.toString() }});
    }}

    installHooks();
    """

    sequence = 0

    def on_message(message, data):
        nonlocal sequence
        if message["type"] != "send":
            print(message, flush=True)
            return

        payload = message["payload"]
        if payload.get("ready"):
            print(f"Attached to PID {payload['pid']} GameAssembly={payload['module']}", flush=True)
            return
        if payload.get("hit"):
            print(f"Hit PID {payload['pid']} RVA {payload['hit']} arg={payload['arg']}", flush=True)
            return
        if payload.get("error"):
            print(payload["error"], flush=True)
            return

        rva = payload.get("rva")
        if rva in ("0x85d9ac0", "0x85d9890") and payload.get("arg") == 1:
            value = (data or b"").hex()
            material["key"] = value
            if value not in material["key_candidates"]:
                material["key_candidates"].append(value)
            save_material(material_path)
            persist_root_material_if_missing()
        elif rva in ("0x85d9ab0", "0x85d9890") and payload.get("arg") == 2:
            value = (data or b"").hex()
            material["iv"] = value
            if value not in material["iv_candidates"]:
                material["iv_candidates"].append(value)
            save_material(material_path)
            persist_root_material_if_missing()

        path = output / f"rva-{payload['rva']}-arg-{payload['arg']}-{sequence:04d}-{payload['length']}.bin"
        sequence += 1
        path.write_bytes(data or b"")
        print(f"Captured {path} from {payload['rva']}", flush=True)

    sessions = []
    attached_pids = set()

    def attach_process(pid):
        session = device.attach(pid)
        script = session.create_script(source)
        script.on("message", on_message)
        script.load()
        sessions.append(session)

    attached_any = False
    missing_since = None
    try:
        while time.monotonic() < deadline:
            if args.stop_file and pathlib.Path(args.stop_file).is_file():
                break
            candidates = [
                candidate
                for candidate in device.enumerate_processes()
                if candidate.name.lower() == args.process.lower()
            ]
            if candidates:
                attached_any = True
                missing_since = None
            elif attached_any and not keep_waiting:
                missing_since = missing_since or time.monotonic()
                if time.monotonic() - missing_since >= 3:
                    break

            for candidate in candidates:
                if candidate.name.lower() == args.process.lower() and candidate.pid not in attached_pids:
                    attached_pids.add(candidate.pid)
                    try:
                        attach_process(candidate.pid)
                    except Exception as error:
                        print(f"Could not attach to PID {candidate.pid}: {error}", flush=True)
            time.sleep(0.25)
    finally:
        save_material(material_path)
        persist_root_material_if_missing()
        for session in sessions:
            session.detach()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Observer failed: {type(error).__name__}: {error}", flush=True)
        if not getattr(sys, "frozen", False):
            raise
    if getattr(sys, "frozen", False) and os.environ.get("JAPANESE_OFFLINE") != "1":
        try:
            input("Capture complete. Press Enter to close... ")
        except EOFError:
            pass
