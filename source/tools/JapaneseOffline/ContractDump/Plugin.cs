using BepInEx;
using BepInEx.Unity.IL2CPP;
using System.Reflection;

namespace JapaneseOfflineContractDump;

// Dumps embedded protobuf FileDescriptorProto bytes for every loaded
// Google.Protobuf contract (e.g. BattleMember fields 24/25/27) so the
// exact Japanese .proto structure can be reconstructed offline.
// Opt-in: set JAPANESE_DUMP_CONTRACTS=1 or pass -dump-contracts.
// Output: <game>/contract-dump/*.bin (one FileDescriptorProto each),
// fields.txt (human-readable message/enum/field listing), manifest.txt.
// The dump contains schema only, no account data.
[BepInPlugin("df.resleriana.japaneseofflinecontractdump", "Japanese Offline Contract Dump", "1.0.0")]
public sealed class Plugin : BasePlugin
{
    private readonly HashSet<string> _dumpedFiles = new(StringComparer.Ordinal);
    private readonly HashSet<Assembly> _scannedAssemblies = new();
    private string _outputDir = string.Empty;
    private readonly List<string> _summary = new();
    private readonly HashSet<string> _reflectionTypes = new(StringComparer.Ordinal);
    private readonly HashSet<string> _descriptorTypes = new(StringComparer.Ordinal);
    private readonly HashSet<string> _protobufAssemblies = new(StringComparer.Ordinal);
    private readonly List<string> _failures = new();
    private readonly HashSet<string> _textDumped = new(StringComparer.Ordinal);
    private readonly HashSet<string> _probedMessages = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<string>> _probeBlocks = new(StringComparer.Ordinal);
    private readonly List<string> _methodSample = new();
    private readonly object _lock = new();
    private string? _byteArrayType;

    public override void Load()
    {
        if (!IsDumpRequested())
        {
            Log.LogInfo("Contract dump not requested (set JAPANESE_DUMP_CONTRACTS=1 or pass -dump-contracts).");
            return;
        }

        _outputDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "contract-dump");
        Directory.CreateDirectory(_outputDir);
        AppDomain.CurrentDomain.AssemblyLoad += (_, __) => DumpNewDescriptors();
        DumpNewDescriptors();
    }

    private static bool IsDumpRequested()
    {
        return Environment.GetEnvironmentVariable("JAPANESE_DUMP_CONTRACTS") == "1"
            || Environment.GetCommandLineArgs().Any(argument =>
                string.Equals(argument, "-dump-contracts", StringComparison.OrdinalIgnoreCase));
    }

    private void DumpNewDescriptors()
    {
        // AssemblyLoad can fire on any thread.
        lock (_lock)
        {
            try
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    if (!_scannedAssemblies.Add(assembly))
                    {
                        continue;
                    }

                    Type[] types;
                    try
                    {
                        types = assembly.GetTypes();
                    }
                    catch (ReflectionTypeLoadException error)
                    {
                        types = error.Types.Where(type => type is not null).Cast<Type>().ToArray();
                    }

                    foreach (var type in types)
                    {
                        DumpFromType(type);
                    }
                }

                WriteProbedFields();
                File.WriteAllLines(Path.Combine(_outputDir, "manifest.txt"), _summary.OrderBy(line => line));
                File.WriteAllLines(Path.Combine(_outputDir, "debug.txt"), DebugLines());
                Log.LogInfo($"CONTRACT-DUMP done; files={_dumpedFiles.Count} probed={_probedMessages.Count} assemblies={_scannedAssemblies.Count} dir={_outputDir}");
            }
            catch (Exception error)
            {
                Log.LogError($"CONTRACT-DUMP failed: {error.GetType().FullName}: {error.Message}");
            }
        }
    }

    private void DumpFromType(Type type)
    {
        if (type is null)
        {
            return;
        }

        var fullName = type.FullName ?? type.Name;
        if (fullName.Contains("Reflection", StringComparison.Ordinal) && _reflectionTypes.Count < 200)
        {
            _reflectionTypes.Add(fullName);
        }

        if (fullName.Contains("Descriptor", StringComparison.Ordinal) && _descriptorTypes.Count < 200)
        {
            _descriptorTypes.Add(fullName);
        }

        // Duck-typed: accept any static parameterless "Descriptor" property,
        // whatever protobuf implementation or namespace the game uses.
        foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
        {
            if (!string.Equals(property.Name, "Descriptor", StringComparison.Ordinal)
                || property.GetIndexParameters().Length != 0)
            {
                continue;
            }

            object? descriptor;
            try
            {
                descriptor = property.GetValue(null, null);
            }
            catch
            {
                continue;
            }

            var file = ToFileDescriptor(descriptor);
            if (file is null)
            {
                continue;
            }

            DumpFileDescriptor(file);
            ProbeMessageClass(type, descriptor);
        }
    }

    private void ProbeMessageClass(Type type, object? descriptor)
    {
        // Message classes (not *Reflection holders) in Blend assemblies.
        // Single-value property reads only: no collections cross interop.
        if (descriptor is null || type.IsAbstract || type.IsInterface)
        {
            return;
        }

        if (type.Name.EndsWith("Reflection", StringComparison.Ordinal))
        {
            return;
        }

        if (!(type.Assembly.FullName ?? string.Empty).Contains("Blend", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        var descriptorType = descriptor.GetType();
        if (!(descriptorType.FullName ?? string.Empty).EndsWith("MessageDescriptor", StringComparison.Ordinal))
        {
            return;
        }

        ProbeMessageDescriptor(descriptor, type.FullName);
    }

    private void ProbeMessageDescriptor(object descriptor, string? fallbackName)
    {
        var descriptorType = descriptor.GetType();
        string? messageName;
        string? fileName;
        try
        {
            messageName = descriptorType.GetProperty("FullName")?.GetValue(descriptor, null) as string
                ?? fallbackName;
            var file = descriptorType.GetProperty("File")?.GetValue(descriptor, null);
            fileName = file?.GetType().GetProperty("Name")?.GetValue(file, null) as string;
        }
        catch
        {
            return;
        }

        if (string.IsNullOrEmpty(messageName) || !_probedMessages.Add(messageName))
        {
            return;
        }

        var lines = new List<string> { $"message {messageName} ({fileName})" };
        ProbeFieldsInto(descriptor, lines);
        _probeBlocks[messageName] = lines;
    }

    private void ProbeFieldsInto(object descriptor, List<string> lines)
    {
        var descriptorType = descriptor.GetType();
        var finder = FindMethod(descriptorType, "FindFieldByNumber", 1);
        if (finder is null)
        {
            lines.Add("  FindFieldByNumber missing");
            return;
        }

        // Open-ended: field numbers can exceed any fixed bound and may
        // contain reserved gaps, so stop only after a long miss run.
        var misses = 0;
        for (var number = 1; number <= 512 && misses < 32; number++)
        {
            object? field;
            try
            {
                field = finder.Invoke(descriptor, new object[] { number });
            }
            catch
            {
                misses++;
                continue;
            }

            if (field is null)
            {
                misses++;
                continue;
            }

            misses = 0;
            try
            {
                var fieldType = field.GetType();
                var fieldName = fieldType.GetProperty("Name")?.GetValue(field, null) as string;
                var kind = fieldType.GetProperty("FieldType")?.GetValue(field, null)?.ToString();
                string? detail = null;
                object? nested = null;
                try
                {
                    if (kind == "Message")
                    {
                        nested = fieldType.GetProperty("MessageType")?.GetValue(field, null);
                        detail = nested?.GetType().GetProperty("FullName")?.GetValue(nested, null) as string;
                    }
                    else if (kind == "Enum")
                    {
                        var enumDescriptor = fieldType.GetProperty("EnumType")?.GetValue(field, null);
                        detail = enumDescriptor?.GetType().GetProperty("FullName")?.GetValue(enumDescriptor, null) as string;
                        ProbeEnum(enumDescriptor);
                    }
                }
                catch
                {
                }

                lines.Add($"  {kind} {fieldName} = {number} ({detail})");
                if (nested is not null)
                {
                    ProbeMessageDescriptor(nested, detail);
                }
            }
            catch
            {
            }
        }
    }

    private void ProbeEnum(object? enumDescriptor)
    {
        if (enumDescriptor is null)
        {
            return;
        }

        var descriptorType = enumDescriptor.GetType();
        string? enumName;
        try
        {
            enumName = descriptorType.GetProperty("FullName")?.GetValue(enumDescriptor, null) as string;
        }
        catch
        {
            return;
        }

        if (string.IsNullOrEmpty(enumName) || !_probedMessages.Add("enum " + enumName))
        {
            return;
        }

        var lines = new List<string> { $"enum {enumName}" };
        var finder = FindMethod(descriptorType, "FindValueByNumber", 1);
        if (finder is null)
        {
            lines.Add("  FindValueByNumber missing");
            _probeBlocks["enum " + enumName] = lines;
            return;
        }

        var misses = 0;
        for (var number = -8; number <= 128 && misses < 16; number++)
        {
            object? value;
            try
            {
                value = finder.Invoke(enumDescriptor, new object[] { number });
            }
            catch
            {
                misses++;
                continue;
            }

            if (value is null)
            {
                misses++;
                continue;
            }

            misses = 0;
            try
            {
                var valueType = value.GetType();
                var valueName = valueType.GetProperty("Name")?.GetValue(value, null) as string;
                lines.Add($"  {valueName} = {number}");
            }
            catch
            {
            }
        }

        _probeBlocks["enum " + enumName] = lines;
    }

    private void WriteProbedFields()
    {
        try
        {
            var lines = new List<string>();
            foreach (var key in _probeBlocks.Keys.OrderBy(key => key))
            {
                lines.AddRange(_probeBlocks[key]);
            }

            File.WriteAllLines(Path.Combine(_outputDir, "fields.txt"), lines);
        }
        catch (Exception error)
        {
            _failures.Add($"fields.txt: {error.GetType().Name} {error.Message}");
        }
    }

    private static object? ToFileDescriptor(object? descriptor)
    {
        if (descriptor is null)
        {
            return null;
        }

        var descriptorType = descriptor.GetType();
        try
        {
            // File descriptor itself: has ToProto().
            if (FindMethod(descriptorType, "ToProto", 0) is not null)
            {
                return descriptor;
            }

            // Message/enum descriptor: follow .File to the file descriptor.
            return descriptorType.GetProperty("File")?.GetValue(descriptor, null);
        }
        catch
        {
            return null;
        }
    }

    private IEnumerable<string> DebugLines()
    {
        yield return $"assemblies={_scannedAssemblies.Count} files={_dumpedFiles.Count} text_files={_textDumped.Count} probed={_probedMessages.Count} failures={_failures.Count} byte_type={_byteArrayType ?? "unknown"}";
        foreach (var failure in _failures.Take(20))
        {
            yield return $"failure: {failure}";
        }
        foreach (var assembly in _scannedAssemblies.OrderBy(assembly => assembly.FullName))
        {
            var name = assembly.FullName ?? "?";
            if (name.Contains("Protobuf", StringComparison.OrdinalIgnoreCase)
                || name.Contains("Blend", StringComparison.OrdinalIgnoreCase)
                || name.Contains("MessagePack", StringComparison.OrdinalIgnoreCase))
            {
                _protobufAssemblies.Add(name);
            }
        }

        yield return $"protobuf_assemblies={_protobufAssemblies.Count}";
        foreach (var name in _protobufAssemblies.OrderBy(name => name).Take(20))
        {
            yield return $"assembly: {name}";
        }

        yield return $"reflection_types={_reflectionTypes.Count}";
        foreach (var name in _reflectionTypes.OrderBy(name => name).Take(80))
        {
            yield return $"reflection: {name}";
        }

        yield return $"descriptor_types={_descriptorTypes.Count}";
        foreach (var name in _descriptorTypes.OrderBy(name => name).Take(80))
        {
            yield return $"descriptor: {name}";
        }

        yield return $"method_sample={_methodSample.Count}";
        foreach (var name in _methodSample.Take(60))
        {
            yield return $"method: {name}";
        }
    }

    private void DumpFileDescriptor(object file)
    {
        string? name;
        try
        {
            name = file.GetType().GetProperty("Name")?.GetValue(file, null) as string;
        }
        catch
        {
            return;
        }

        if (string.IsNullOrEmpty(name) || _dumpedFiles.Contains(name))
        {
            return;
        }

        SampleMethods(file);

        try
        {
            var proto = FindMethod(file.GetType(), "ToProto", 0)?.Invoke(file, null);
            if (proto is not null && _textDumped.Add(name))
            {
                // Text format is a plain string: crosses IL2CPP interop
                // reliably even when byte[] does not. Parse offline with
                // google.protobuf.text_format into FileDescriptorProto.
                try
                {
                    var text = FindMethod(proto.GetType(), "ToString", 0)?.Invoke(proto, null) as string;
                    if (!string.IsNullOrEmpty(text))
                    {
                        File.WriteAllText(Path.Combine(_outputDir, name.Replace('/', '_') + ".txt"), text);
                        _summary.Add($"{name} text={text.Length}");
                        Log.LogInfo($"CONTRACT-DUMP wrote {name}.txt chars={text.Length}");
                    }
                    else
                    {
                        _failures.Add($"{name}.txt: ToString missing or empty");
                    }
                }
                catch (Exception error)
                {
                    _failures.Add($"{name}.txt: {error.GetType().Name} {error.Message}");
                }

            }

            var raw = proto is null ? null : FindMethod(proto.GetType(), "ToByteArray", 0)?.Invoke(proto, null);
            if (raw is not null && _byteArrayType is null)
            {
                _byteArrayType = raw.GetType().FullName;
                Log.LogInfo($"CONTRACT-DUMP byte array type: {_byteArrayType}");
            }

            var bytes = ToByteArray(raw);
            if (bytes is null)
            {
                _failures.Add($"{name}: could not marshal ToByteArray result ({raw?.GetType().FullName ?? "null"})");
                Log.LogError($"CONTRACT-DUMP no bytes for {name}");
                return;
            }

            File.WriteAllBytes(Path.Combine(_outputDir, name.Replace('/', '_') + ".bin"), bytes);
            _dumpedFiles.Add(name);
            _summary.Add($"{name} bytes={bytes.Length}");
            Log.LogInfo($"CONTRACT-DUMP wrote {name} bytes={bytes.Length}");
        }
        catch (Exception error)
        {
            _failures.Add($"{name}: {error.GetType().Name} {error.Message}");
            Log.LogError($"CONTRACT-DUMP failed for {name}: {error.Message}");
        }
    }

    private static MethodInfo? FindMethod(Type type, string name, int parameterCount)
    {
        // GetMethod(name, Type.EmptyTypes) can miss on interop types;
        // match by name and arity instead.
        try
        {
            return type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)
                .FirstOrDefault(method => method.Name == name && method.GetParameters().Length == parameterCount);
        }
        catch
        {
            return null;
        }
    }

    private void SampleMethods(object file)
    {
        if (_methodSample.Count > 0)
        {
            return;
        }

        try
        {
            foreach (var method in file.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static).Take(60))
            {
                _methodSample.Add($"{method.Name}({method.GetParameters().Length})");
            }
        }
        catch
        {
        }
    }

    private static byte[]? ToByteArray(object? value)
    {
        if (value is byte[] direct)
        {
            return direct;
        }

        if (value is Array managed)
        {
            try
            {
                var copy = new byte[managed.Length];
                Array.Copy(managed, copy, managed.Length);
                return copy;
            }
            catch
            {
            }
        }

        if (value is System.Collections.IEnumerable sequence)
        {
            try
            {
                return sequence.Cast<byte>().ToArray();
            }
            catch
            {
            }
        }

        // IL2CPP arrays may expose Length/GetValue without managed interfaces.
        try
        {
            if (value is null)
            {
                return null;
            }

            var valueType = value.GetType();
            var length = (int?)valueType.GetProperty("Length")?.GetValue(value, null)
                ?? (int?)valueType.GetProperty("Count")?.GetValue(value, null);
            var getter = valueType.GetMethod("GetValue", new[] { typeof(int) });
            if (length is null || getter is null)
            {
                return null;
            }

            var copy = new byte[length.Value];
            for (var index = 0; index < copy.Length; index++)
            {
                copy[index] = Convert.ToByte(getter.Invoke(value, new object[] { index }));
            }

            return copy;
        }
        catch
        {
            return null;
        }
    }

    private static string? ReadString(object? value)
    {
        return value?.ToString();
    }
}
