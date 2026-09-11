using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using System.Reflection;

namespace JapaneseOfflineClientRequestDiagnostics;

[BepInPlugin("df.resleriana.japaneseofflinediagnostics", "Japanese Offline Client Request Diagnostics", "1.0.0")]
public sealed class Plugin : BasePlugin
{
    public override void Load()
    {
        if (!IsOfflineLaunch())
        {
            Log.LogInfo("Client request diagnostics inactive for online launch.");
            return;
        }

        var loggedTypes = new HashSet<string>(StringComparer.Ordinal);
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
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
                var fullName = type.FullName ?? type.Name;
                if (!fullName.Contains("Character", StringComparison.OrdinalIgnoreCase)
                    && !fullName.Contains("Costume", StringComparison.OrdinalIgnoreCase)
                    && !fullName.Contains("Skin", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                if (loggedTypes.Add(fullName))
                {
                    LogApiMethods(type);
                }
            }
        }
    }

    private bool IsOfflineLaunch()
    {
        return Environment.GetEnvironmentVariable("JAPANESE_OFFLINE") == "1"
            || Environment.GetCommandLineArgs().Any(argument =>
                string.Equals(argument, "-japanese-offline", StringComparison.OrdinalIgnoreCase));
    }

    private void LogApiMethods(Type type)
    {
        if (type is null)
        {
            return;
        }

        Log.LogInfo($"Inspecting client request type {type.FullName}");
        foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                     .Where(method => IsCandidate(method.Name)))
        {
            var parameters = string.Join(", ", method.GetParameters().Select(parameter =>
                $"{parameter.ParameterType.FullName} {parameter.Name}"));
            Log.LogInfo($"CLIENT-REQUEST-CANDIDATE {method.Name}({parameters}) -> {method.ReturnType.FullName}");
        }
    }

    private static bool IsCandidate(string methodName)
    {
        return methodName.Contains("skin", StringComparison.OrdinalIgnoreCase)
            || methodName.Contains("costume", StringComparison.OrdinalIgnoreCase)
            || methodName.Contains("character", StringComparison.OrdinalIgnoreCase)
            || methodName.Contains("request", StringComparison.OrdinalIgnoreCase);
    }
}
