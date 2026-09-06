using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using Cysharp.Threading.Tasks;
using HarmonyLib;
using System.Reflection;

namespace JapaneseOfflineEvents;

[BepInPlugin("df.resleriana.japaneseofflineevents", "Japanese Offline Events", "1.0.0")]
public sealed class Plugin : BasePlugin
{
    private static readonly HashSet<int> NonRevivalEventIds = new()
    {
        7, 10, 12, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33,
        38, 40, 44, 45, 46, 47, 48, 49, 50, 52, 53, 54, 55, 56, 57, 58, 59, 60, 62,
        63, 64, 66, 67, 70, 73, 75, 76, 80, 81, 83, 85, 86, 88, 91, 93, 97, 99, 100,
        101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116,
        117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132,
        133, 134, 136, 138, 139, 140, 141, 142, 146, 148, 149, 150, 151, 152, 153, 154,
        155, 157, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172,
        173, 174, 983,
    };
    private static ManualLogSource? log;
    private static bool historicalMasterDataGatePending;
    private static readonly HashSet<int> sourceEventDateOverrideLogged = new();
    private static readonly HashSet<int> episodeDateOverrideLogged = new();
    private static int expeditionTimelineIndex;
    private static readonly (long First, long Second)[] ExpeditionTimelineKeys =
    {
        (8474723593597338938L, 2304692465143954913L),
        (2773027068281725200L, 4888269225604980159L),
        (3291209363939324586L, 6367800330248979107L),
    };

    public override void Load()
    {
        log = Log;
        if (!IsOfflineLaunch())
        {
            Log.LogInfo("Japanese offline event patch inactive for online launch.");
            return;
        }

        var harmony = new Harmony("df.resleriana.japaneseofflineevents");
        PatchExpeditionTimelineSelection(harmony);
        PatchBoolean(harmony, typeof(EHPBANEAIPE), "MFKPEBOEEMH", "event availability");

        foreach (var methodName in new[]
        {
            "APNKEHCMFEG",
            "ICEHJDMLMFA",
            "PNCIJAGOJOE",
            "BDEFBLNBGAN",
        })
        {
            PatchBoolean(harmony, typeof(EventTopMenuWindow), methodName, "event menu predicate");
        }

        PatchBooleanFalse(harmony, typeof(EventContentsButton), "OENCJPNDCMK", "event content lock predicate");
        PatchBooleanFalse(harmony, typeof(EventContentsButton), "GKBGFLDNNPO", "event content lock predicate");

        var episodeAvailability = AccessTools.Method(typeof(CENMDLNOIBJ), "MFKPEBOEEMH");
        if (episodeAvailability is not null)
        {
            harmony.Patch(episodeAvailability, postfix: new HarmonyMethod(typeof(Plugin), nameof(AllowNonRevivalEpisode)));
            Log.LogInfo($"Patched offline non-revival episode availability source: {episodeAvailability}");
        }

        foreach (var methodName in new[]
        {
            "JPBOCPJEOMP",
        })
        {
            PatchBoolean(harmony, typeof(EventStoryMenuWindow), methodName, "event chapter predicate");
        }

        foreach (var methodName in new[]
        {
            "CIBDMLDJCNM",
            "MBDOLOCIKFP",
            "AJKJCJGDFPP",
        })
        {
            PatchBoolean(harmony, typeof(DOFENPOABBN), methodName, "event extension predicate");
        }

        var collectionFilters = AccessTools.TypeByName("LOMOOCBJIHO+__c");
        if (collectionFilters is null)
        {
            Log.LogWarning("Could not find the offline event collection filter type.");
            return;
        }

        foreach (var methodName in new[]
        {
            "EONLFIILHHG",
            "NEMJMFDKCCI",
            "FDKNNJOKGBH",
        })
        {
            PatchBoolean(harmony, collectionFilters, methodName, "event collection filter");
        }

        var finishMethod = AccessTools.Method(
            AccessTools.TypeByName("Api.QuestApi"),
            "RequestQuestTalkEventFinishInternal");
        if (finishMethod is null)
        {
            Log.LogWarning("Could not find the offline talk-event completion request.");
        }
        else
        {
            harmony.Patch(finishMethod, prefix: new HarmonyMethod(typeof(Plugin), nameof(BypassTalkEventFinish)));
            Log.LogInfo($"Bypassed offline talk-event completion request: {finishMethod}");
        }

        var recipeLearnMethod = AccessTools.Method(
            AccessTools.TypeByName("Api.RecipeApi"),
            "RequestRecipeLearnInternal");
        if (recipeLearnMethod is null)
        {
            Log.LogWarning("Could not find the offline recipe learn request.");
        }
        else
        {
            harmony.Patch(recipeLearnMethod, prefix: new HarmonyMethod(typeof(Plugin), nameof(BypassRecipeLearn)));
            Log.LogInfo($"Bypassed offline recipe learn request: {recipeLearnMethod}");
        }

        var questCanStart = AccessTools.PropertyGetter(typeof(Blend.UserData.QuestState), "CanStart");
        if (questCanStart is not null)
        {
            harmony.Patch(questCanStart, postfix: new HarmonyMethod(typeof(Plugin), nameof(AllowHistoricalTalkQuestStart)));
            Log.LogInfo($"Patched offline historical talk quest start gate: {questCanStart}");
        }

        var questMasterDataGate = AccessTools.Method(typeof(ELFDHIPPOGO), "MFKPEBOEEMH");
        if (questMasterDataGate is not null)
        {
            harmony.Patch(questMasterDataGate, postfix: new HarmonyMethod(typeof(Plugin), nameof(AllowPendingHistoricalMasterData)));
            Log.LogInfo($"Patched offline pending historical master-data gate: {questMasterDataGate}");
        }

    }

    private static void PatchExpeditionTimelineSelection(Harmony harmony)
    {
        foreach (var methodName in new[] { "SelectExpeditionTimeline", "JJODJJHGCPM", "JBAKAEOMOKC" })
        {
            var method = AccessTools.Method(typeof(HomeMenuScenePerform), methodName);
            if (method is null)
                continue;
            try
            {
                harmony.Patch(method, postfix: new HarmonyMethod(typeof(Plugin), nameof(RotateExpeditionTimeline)));
                log?.LogInfo($"Patched offline Expedition timeline selector: {method}");
            }
            catch (Exception error)
            {
                log?.LogWarning($"Could not patch offline Expedition timeline selector {method}: {error.Message}");
            }
        }
    }

    private static void RotateExpeditionTimeline(ref HomeMenuScenePerform.DIDFNDGNMDN __result)
    {
        var markerPath = Path.Combine(Paths.GameRootPath, "offline-expedition-timeline-request.txt");
        if (!File.Exists(markerPath))
            return;

        try
        {
            File.Delete(markerPath);
        }
        catch (Exception error)
        {
            log?.LogWarning($"Could not consume offline Expedition timeline marker: {error.Message}");
        }

        var index = expeditionTimelineIndex++ % ExpeditionTimelineKeys.Length;
        var key = ExpeditionTimelineKeys[index];
        __result = new HomeMenuScenePerform.DIDFNDGNMDN(key.First, key.Second);
        log?.LogInfo(
            $"Selected offline Expedition timeline index={index} "
            + $"key={key.First}/{key.Second}");
    }

    private void PatchBoolean(Harmony harmony, Type type, string methodName, string category)
    {
        var method = AccessTools.Method(type, methodName);
        if (method is null)
        {
            Log.LogWarning($"Could not find {category}: {type.FullName}.{methodName}");
            return;
        }

        PatchBoolean(harmony, method, category);
    }

    private void PatchBoolean(Harmony harmony, MethodBase method, string category)
    {
        harmony.Patch(method, postfix: new HarmonyMethod(typeof(Plugin), nameof(ForceBooleanTrue)));
        Log.LogInfo($"Patched offline {category}: {method}");
    }

    private void PatchBooleanFalse(Harmony harmony, Type type, string methodName, string category)
    {
        var method = AccessTools.Method(type, methodName);
        if (method is null)
        {
            Log.LogWarning($"Could not find {category}: {type.FullName}.{methodName}");
            return;
        }

        harmony.Patch(method, postfix: new HarmonyMethod(typeof(Plugin), nameof(ForceBooleanFalse)));
        Log.LogInfo($"Patched offline {category}: {method}");
    }

    private static bool IsOfflineLaunch()
    {
        return string.Equals(Environment.GetEnvironmentVariable("JAPANESE_OFFLINE"), "1", StringComparison.Ordinal)
            || Environment.GetCommandLineArgs().Any(argument => string.Equals(argument, "-japanese-offline", StringComparison.OrdinalIgnoreCase));
    }

    public static void ForceBooleanTrue(ref bool __result)
    {
        __result = true;
    }

    public static void ForceBooleanFalse(ref bool __result)
    {
        __result = false;
    }

    public static void AllowNonRevivalEpisode(CENMDLNOIBJ __instance, ref bool __result)
    {
        if (__instance is null)
        {
            return;
        }

        try
        {
            int episodeId = (int)__instance.KGKGDIMKLOL;
            int eventId = episodeId / 100;
            if (!NonRevivalEventIds.Contains(eventId))
            {
                return;
            }

            var futureDate = new Il2CppSystem.Nullable<_ee847>(
                new _ee847(new Il2CppSystem.DateTime(new DateTime(2100, 1, 1, 0, 0, 0, DateTimeKind.Utc).Ticks)));
            __instance._DJIEFLOPFEB_k__BackingField = futureDate;
            __result = true;
            if (episodeDateOverrideLogged.Add(episodeId))
            {
                log?.LogInfo($"Overrode non-revival episode {episodeId} end_at and availability source for event {eventId}.");
            }
        }
        catch (Exception error)
        {
            log?.LogWarning($"Could not override non-revival episode availability source: {error.GetType().Name}");
        }
    }

    public static void AllowHistoricalTalkQuestStart(Blend.UserData.QuestState __instance, ref bool __result)
    {
        if (__instance is null)
        {
            return;
        }

        int questId = __instance.QuestIdValue;
        bool nonRevivalEvent = NonRevivalEventIds.Contains(questId / 100000);
        try
        {
            nonRevivalEvent |= IsNonRevivalEvent(__instance.MasterData?.FHKCJJPMDNL);
        }
        catch (Exception error)
        {
            log?.LogDebug($"Could not resolve event ID for quest_id={questId}: {error.GetType().Name}");
        }

        if (nonRevivalEvent)
        {
            log?.LogInfo($"Historical CanStart quest_id={questId} is_talk_event={__instance.IsTalkEvent} original={__result}");
            historicalMasterDataGatePending = true;
            __result = true;
        }
    }

    public static void AllowPendingHistoricalMasterData(ELFDHIPPOGO __instance, ref bool __result)
    {
        if (!historicalMasterDataGatePending || __instance is null)
        {
            return;
        }

        try
        {
            var eventData = __instance.FHKCJJPMDNL;
            if (IsNonRevivalEvent(eventData))
            {
                OverrideNonRevivalEventDates(eventData);
                OverrideHistoricalQuestEndDate(__instance, GetEventId(eventData));
                historicalMasterDataGatePending = false;
                log?.LogInfo($"Allowed non-revival historical master-data gate; original={__result}");
                __result = true;
            }
        }
        catch (Exception error)
        {
            log?.LogWarning($"Could not inspect pending historical master data: {error.GetType().Name}");
        }
    }

    private static bool IsNonRevivalEvent(EHPBANEAIPE? eventData)
    {
        return eventData is not null && NonRevivalEventIds.Contains(GetEventId(eventData));
    }

    private static int GetEventId(EHPBANEAIPE eventData)
    {
        return eventData.OCGCKNJJDKL;
    }

    private static void OverrideNonRevivalEventDates(EHPBANEAIPE eventData)
    {
        try
        {
            int eventId = GetEventId(eventData);
            var futureDate = new Il2CppSystem.Nullable<_ee847>(
                new _ee847(new Il2CppSystem.DateTime(new DateTime(2100, 1, 1, 0, 0, 0, DateTimeKind.Utc).Ticks)));
            eventData._DJIEFLOPFEB_k__BackingField = futureDate;
            eventData._GNDKDJOHLIB_k__BackingField = futureDate;
            if (sourceEventDateOverrideLogged.Add(eventId))
            {
                log?.LogInfo($"Overrode non-revival event {eventId} end_at and reward_end_at backing fields.");
            }
        }
        catch (Exception error)
        {
            log?.LogWarning($"Could not override non-revival event master-data dates: {error.GetType().Name}");
        }
    }

    private static void OverrideHistoricalQuestEndDate(ELFDHIPPOGO masterData, int eventId)
    {
        try
        {
            var futureDate = new Il2CppSystem.Nullable<_ee847>(
                new _ee847(new Il2CppSystem.DateTime(new DateTime(2100, 1, 1, 0, 0, 0, DateTimeKind.Utc).Ticks)));
            masterData._DJIEFLOPFEB_k__BackingField = futureDate;
            log?.LogInfo($"Overrode non-revival event {eventId} quest master-data end_at backing field.");
        }
        catch (Exception error)
        {
            log?.LogWarning($"Could not override non-revival event {eventId} quest master-data end_at: {error.GetType().Name}");
        }
    }

    public static bool BypassTalkEventFinish(
        ref UniTask<Blend.ApiSchema.Api.QuestTalkEventFinishResponse> __result,
        Blend.ApiSchema.Api.QuestTalkEventFinishRequest arg)
    {
        var response = new Blend.ApiSchema.Api.QuestTalkEventFinishResponse();
        if (arg is not null)
        {
            var changedResources = new Blend.ApiSchema.Model.Resources();
            changedResources.QuestStates.Add(new Blend.ApiSchema.Model.QuestState
            {
                QuestId = arg.QuestId,
                ClearCount = 1,
            });
            response.ChangedResources = changedResources;
            log?.LogInfo($"Applied offline story completion state for quest_id={arg.QuestId}");
        }

        __result = UniTask.FromResult(response);
        return false;
    }

    public static bool BypassRecipeLearn(
        ref UniTask<Blend.ApiSchema.Api.RecipeLearnResponse> __result)
    {
        var response = new Blend.ApiSchema.Api.RecipeLearnResponse
        {
            ChangedResources = new Blend.ApiSchema.Model.Resources(),
        };
        __result = UniTask.FromResult(response);
        log?.LogInfo("Bypassed offline recipe learn request; using recipes from profile.bin.");
        return false;
    }
}
