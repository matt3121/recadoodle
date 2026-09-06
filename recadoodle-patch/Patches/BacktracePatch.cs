using System;
using System.Collections.Generic;
using Backtrace.Unity.Json;
using Backtrace.Unity.Model;
using HarmonyLib;
using UnityEngine.Networking;

namespace Recadoodle.Patches;

// Backtrace crash reporting — the uploads to submit.backtrace.io.
//
// This one does not go through BestHTTP, so `AmplitudePatch`'s host block never sees it:
// `Backtrace.Unity.dll` references `UnityEngine.UnityWebRequestModule` and nothing else HTTP-shaped.
// The whole SDK is unobfuscated (it's a third-party package, so no per-build name churn to survive),
// and every submission it makes — crash reports, minidumps, metrics — funnels through the four
// `BacktraceHttpClient.Post` overloads. That's the concrete class; `IBacktraceHttpClient` is the
// interface and patching it would silently never run.
//
// The two overload shapes need different treatment, because of who owns the send:
//
//   void Post(url, jObject, onComplete)   - fire-and-forget, the SDK sends internally. We skip it and
//                                           invoke the callback with a 200 ourselves.
//   UnityWebRequest Post(...)  x3         - builds the request and hands it back; *the caller* sends it
//                                           (`yield return request.SendWebRequest()`). Skipping the
//                                           original would hand the caller a null to dereference, so
//                                           instead we let it build whatever it likes and repoint the
//                                           finished request at a black hole.
//
// Not covered: `RecRoomNativeClient` installs a native crash handler, and a minidump uploaded from
// native code on the next launch never passes through here. If submit.backtrace.io still shows a
// multipart minidump POST with everything below firing, that's the path it took.
[HarmonyPatch]
public static class BacktracePatch
{
    // Loopback port 1: nothing listens there, so the send fails with connection-refused in
    // microseconds without a packet leaving the machine, and the SDK takes its ordinary offline path.
    private const string BlackHoleUrl = "http://127.0.0.1:1/blocked-by-recnet-plugin";

    private static readonly HashSet<string> _loggedBlocked = new();

    // Fire-and-forget path (metrics). The SDK sends this one itself, so skipping the original is
    // enough — but the callback has to be answered or the submission queue keeps the batch it just
    // handed us and retries it forever. (statusCode, isError, response): a 200 with no error is what
    // it waits for before clearing the batch.
    [HarmonyPrefix]
    [HarmonyPatch(typeof(BacktraceHttpClient), nameof(BacktraceHttpClient.Post),
        typeof(string), typeof(BacktraceJObject), typeof(Il2CppSystem.Action<long, bool, string>))]
    private static bool PostWithCallbackPrefix(string __0, Il2CppSystem.Action<long, bool, string> __2)
    {
        if (!Plugin.DisableTelemetry.Value)
            return true;

        LogBlocked(__0);
        __2?.Invoke(200, false, "{}");
        return false;
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(BacktraceHttpClient), nameof(BacktraceHttpClient.Post),
        typeof(string), typeof(BacktraceJObject))]
    private static void PostJObjectPostfix(string __0, UnityWebRequest __result) => Neuter(__0, __result);

    [HarmonyPostfix]
    [HarmonyPatch(typeof(BacktraceHttpClient), nameof(BacktraceHttpClient.Post),
        typeof(string), typeof(string),
        typeof(Il2CppSystem.Collections.Generic.IEnumerable<string>),
        typeof(Il2CppSystem.Collections.Generic.IDictionary<string, string>))]
    private static void PostJsonPostfix(string __0, UnityWebRequest __result) => Neuter(__0, __result);

    [HarmonyPostfix]
    [HarmonyPatch(typeof(BacktraceHttpClient), nameof(BacktraceHttpClient.Post),
        typeof(string), typeof(Il2CppSystem.Collections.Generic.List<IMultipartFormSection>))]
    private static void PostFormPostfix(string __0, UnityWebRequest __result) => Neuter(__0, __result);

    // Leave the request the SDK built exactly as it is — handlers, headers, body — and change only
    // where it points. Rebuilding it ourselves would mean guessing which handlers the caller goes on
    // to dereference; this way the coroutine keeps its shape and just gets an error back.
    private static void Neuter(string url, UnityWebRequest request)
    {
        if (!Plugin.DisableTelemetry.Value || request == null)
            return;

        LogBlocked(url);
        request.url = BlackHoleUrl;
    }

    // Once per host normally, every submission under [Advanced] Debug — same rule as the analytics
    // host block, and for the same reason: a deduped line can't answer "did *this* upload get
    // dropped?" when you're staring at a proxy trace.
    private static void LogBlocked(string url)
    {
        if (Plugin.Debug.Value)
        {
            Plugin.Log.LogInfo($"[BACKTRACE] dropped submission to {url}");
            return;
        }

        var host = HostOf(url);
        if (_loggedBlocked.Add(host))
            Plugin.Log.LogInfo($"[BACKTRACE] telemetry disabled — dropping submissions to {host}");
    }

    private static string HostOf(string url)
    {
        try
        {
            return new Uri(url).Host;
        }
        catch (Exception)
        {
            return url;
        }
    }
}
