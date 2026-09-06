using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using BestHTTP;
using BestHTTP.SecureProtocol.Org.BouncyCastle.Crypto.Tls;
using HarmonyLib;
using System.Reflection;
using UnityEngine.Networking;

namespace JapaneseOfflineProxy;

[BepInPlugin("df.resleriana.japaneseofflineproxy", "Japanese Offline Proxy", "1.0.0")]
public sealed class Plugin : BasePlugin
{
    private const string ProxyHost = "http://127.0.0.1:8080";
    private static ManualLogSource? log;
    private static bool bestHttpConfigured;

    public override void Load()
    {
        log = Log;
        if (!IsOfflineLaunch())
        {
            Log.LogInfo("Japanese offline proxy inactive for online launch.");
            return;
        }

        var harmony = new Harmony("df.resleriana.japaneseofflineproxy");

        var setHeader = typeof(HTTPRequest).GetMethod("SetHeader", BindingFlags.Instance | BindingFlags.Public);
        if (setHeader is not null)
            harmony.Patch(setHeader, postfix: new HarmonyMethod(typeof(Plugin), nameof(ConfigureBestHttp)));
        else
            Log.LogError("Could not find BestHTTP.HTTPRequest.SetHeader");

        var sendWebRequest = typeof(UnityWebRequest).GetMethod("SendWebRequest", BindingFlags.Instance | BindingFlags.Public);
        if (sendWebRequest is not null)
        {
            harmony.Patch(sendWebRequest, prefix: new HarmonyMethod(typeof(Plugin), nameof(RewriteUnityRequest)));
            Log.LogInfo("Patched UnityWebRequest.SendWebRequest for Japanese offline replay.");
        }
        else
        {
            Log.LogError("Could not find UnityWebRequest.SendWebRequest");
        }
    }

    private static bool IsOfflineLaunch()
    {
        return string.Equals(Environment.GetEnvironmentVariable("JAPANESE_OFFLINE"), "1", StringComparison.Ordinal)
            || Environment.GetCommandLineArgs().Any(argument => string.Equals(argument, "-japanese-offline", StringComparison.OrdinalIgnoreCase));
    }

    public static void ConfigureBestHttp()
    {
        if (bestHttpConfigured)
            return;

        HTTPManager.DefaultCertificateVerifyer = new AlwaysValidVerifyer().Cast<ICertificateVerifyer>();
        HTTPManager.Proxy = new HTTPProxy(new Il2CppSystem.Uri(ProxyHost), null, true);
        bestHttpConfigured = true;
        log?.LogInfo($"BestHTTP redirected to {ProxyHost}");
    }

    public static void RewriteUnityRequest(UnityWebRequest __instance)
    {
        var url = __instance.url;
        if (string.IsNullOrEmpty(url))
            return;

        Uri uri;
        try
        {
            uri = new Uri(url);
        }
        catch
        {
            return;
        }

        if (!uri.Host.EndsWith(".resleriana.jp", StringComparison.OrdinalIgnoreCase)
            && !uri.Host.Equals("resleriana.jp", StringComparison.OrdinalIgnoreCase))
            return;

        __instance.SetRequestHeader("X-Offline-Original-Host", uri.Host);
        __instance.SetRequestHeader("X-Offline-Original-Scheme", uri.Scheme);
        __instance.url = $"{ProxyHost}{uri.PathAndQuery}";
        log?.LogInfo($"UnityWebRequest redirected: {uri.Host}{uri.PathAndQuery}");
    }
}
