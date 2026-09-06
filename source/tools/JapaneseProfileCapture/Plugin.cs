using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using BestHTTP;
using HarmonyLib;
using Il2CppInterop.Runtime;
using System.Text.Json;
using System.Reflection;
using System.Threading;

namespace JapaneseProfileCapture;

[BepInPlugin("df.resleriana.japaneseprofilecapture", "Japanese Profile Capture", "1.0.0")]
public sealed class Plugin : BasePlugin
{
    private const string LoginUrl = "https://game.resleriana.jp/user/log_in";
    private static ManualLogSource? log;
    private static Harmony? harmony;
    private static int responseNumber;
    private static string sessionDirectory = string.Empty;

    public override void Load()
    {
        log = Log;
        if (IsOfflineLaunch())
        {
            Log.LogInfo("Japanese profile capture inactive for offline launch; preserving the existing profile.bin.");
            return;
        }

        sessionDirectory = CreateSessionDirectory();
        File.WriteAllText(
            Path.Combine(sessionDirectory, "session.txt"),
            $"STARTED_UTC={DateTime.UtcNow:O}{Environment.NewLine}HOST=game.resleriana.jp{Environment.NewLine}");

        harmony = new Harmony("df.resleriana.japaneseprofilecapture");
        var send = typeof(HTTPRequest).GetMethod("Send", BindingFlags.Instance | BindingFlags.Public);
        if (send is null)
        {
            Log.LogError("Could not find BestHTTP.HTTPRequest.Send");
            return;
        }

        harmony.Patch(send, prefix: new HarmonyMethod(typeof(Plugin), nameof(OnRequestSend)));
        Log.LogInfo($"Watching {LoginUrl}; session capture directory: {sessionDirectory}");

    }

    private static bool IsOfflineLaunch()
    {
        return string.Equals(Environment.GetEnvironmentVariable("JAPANESE_OFFLINE"), "1", StringComparison.Ordinal)
            || Environment.GetCommandLineArgs().Any(argument => string.Equals(argument, "-japanese-offline", StringComparison.OrdinalIgnoreCase));
    }

    private static string CreateSessionDirectory()
    {
        var root = Path.Combine(Paths.GameRootPath, "japanese-capture");
        Directory.CreateDirectory(root);

        var name = $"session-{DateTime.UtcNow:yyyyMMdd-HHmmss-fff}";
        var directory = Path.Combine(root, name);
        var suffix = 1;
        while (Directory.Exists(directory))
        {
            directory = Path.Combine(root, $"{name}-{suffix}");
            suffix++;
        }

        Directory.CreateDirectory(directory);
        return directory;
    }

    public static void OnRequestSend(HTTPRequest __instance)
    {
        try
        {
            var url = __instance.CurrentUri?.ToString();
            if (url is null || !url.StartsWith("https://game.resleriana.jp/", StringComparison.OrdinalIgnoreCase))
                return;

            var callback = DelegateSupport.ConvertDelegate<OnRequestFinishedDelegate>(new Action<HTTPRequest, HTTPResponse>(CaptureResponse));
            __instance.Callback = __instance.Callback + callback;
            log?.LogInfo($"Attached response capture: {url}");
        }
        catch (Exception ex)
        {
            log?.LogError($"Could not attach login response capture: {ex}");
        }
    }

    public static void CaptureResponse(HTTPRequest request, HTTPResponse response)
    {
        try
        {
            var url = request.CurrentUri?.ToString() ?? "unknown";
            if (response is null)
            {
                log?.LogWarning($"Request failed without an HTTP response: {url}");
                return;
            }

            var data = response.Data;
            var number = Interlocked.Increment(ref responseNumber);
            var metadataPath = Path.Combine(sessionDirectory, $"{number:D4}.txt");
            var dataPath = Path.Combine(sessionDirectory, $"{number:D4}-response.bin");
            var requestPath = Path.Combine(sessionDirectory, $"{number:D4}-request.bin");
            var requestHeaders = string.Empty;
            var requestBody = request.GetEntityBody();
            try
            {
                requestHeaders = request.DumpHeaders();
            }
            catch (Exception ex)
            {
                requestHeaders = $"<unavailable: {ex.Message}>";
            }

            if (requestBody is not null)
                File.WriteAllBytes(requestPath, requestBody);

            File.WriteAllText(
                metadataPath,
                $"URL={url}{Environment.NewLine}" +
                $"METHOD={request.MethodType}{Environment.NewLine}" +
                $"STATUS={response.StatusCode}{Environment.NewLine}" +
                $"REQUEST_BYTES={requestBody?.Length ?? 0}{Environment.NewLine}" +
                $"RESPONSE_BYTES={data?.Length ?? 0}{Environment.NewLine}" +
                $"REQUEST_HEADERS_BEGIN{Environment.NewLine}{requestHeaders}{Environment.NewLine}REQUEST_HEADERS_END{Environment.NewLine}");
            if (data is not null)
                File.WriteAllBytes(dataPath, data);

            log?.LogInfo($"Captured session response #{number}: {url} status={response.StatusCode} bytes={data?.Length ?? 0}");

            if (string.Equals(url, LoginUrl, StringComparison.OrdinalIgnoreCase)
                && response.StatusCode == 200
                && data is not null)
            {
                var path = Path.Combine(sessionDirectory, "profile.bin");
                var temporaryPath = path + ".tmp";
                File.WriteAllBytes(temporaryPath, data);
                File.Move(temporaryPath, path, true);
                log?.LogInfo($"Captured Japanese profile in session backup: {path}");

                var rootProfilePath = Path.Combine(Paths.GameRootPath, "profile.bin");
                if (!File.Exists(rootProfilePath))
                {
                    try
                    {
                        File.Copy(path, rootProfilePath, overwrite: false);
                        log?.LogInfo($"Created initial game-root profile: {rootProfilePath}");
                    }
                    catch (IOException) when (File.Exists(rootProfilePath))
                    {
                        log?.LogInfo($"Preserved profile created by another online session: {rootProfilePath}");
                    }
                }
                else
                {
                    log?.LogInfo($"Preserved existing game-root profile: {rootProfilePath}");
                }

                CopySessionMaterialToRoot();
            }
        }
        catch (Exception ex)
        {
            log?.LogError($"Could not save captured response: {ex}");
        }
    }

    private static void CopySessionMaterialToRoot()
    {
        var sessionMaterialPath = Path.Combine(sessionDirectory, "aes-material.json");
        if (!File.Exists(sessionMaterialPath) || !HasCompleteMaterial(sessionMaterialPath))
            return;

        var rootMaterialPath = Path.Combine(Paths.GameRootPath, "aes-material.json");
        var temporaryPath = rootMaterialPath + ".tmp";
        try
        {
            File.Copy(sessionMaterialPath, temporaryPath, true);
            File.Move(temporaryPath, rootMaterialPath, true);
            log?.LogInfo($"Saved profile AES material beside game-root profile: {rootMaterialPath}");
        }
        catch (Exception ex)
        {
            log?.LogWarning($"Could not save game-root profile AES material: {ex.Message}");
            try
            {
                if (File.Exists(temporaryPath))
                    File.Delete(temporaryPath);
            }
            catch
            {
                // Preserve the original capture error without masking it with cleanup failure.
            }
        }
    }

    private static bool HasCompleteMaterial(string path)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            return root.TryGetProperty("key", out var key)
                && key.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(key.GetString())
                && root.TryGetProperty("iv", out var iv)
                && iv.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(iv.GetString());
        }
        catch (Exception)
        {
            return false;
        }
    }

}
