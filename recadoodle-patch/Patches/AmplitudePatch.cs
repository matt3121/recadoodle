using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using BestHTTP;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace Recadoodle.Patches;

// Amplitude analytics: the client ships telemetry to Amplitude, which a self-hosted setup has no use
// for (and which leaks play data off-box). Prefix every event-logging entrypoint and swallow the call
// so nothing is ever queued, batched or sent.
//
// One knob for all telemetry, `[Analytics] Disable Telemetry`, default true — it gates this file plus
// BacktracePatch and UnityTelemetryPatch. Deliberately not split per vendor: nobody wants Amplitude
// gone but the collector alive, and four switches for one intention is four ways to be half-configured.
//
// Target resolution: AmplitudeAnalytics.AmplitudeAnalyticsClient in RecRoom.Analytics.Runtime.dll,
// concrete (it derives from SingletonMonoBehaviour<T>, so there is no abstract-interface dispatch
// trap here). All five Log* names are unobfuscated in the 20230414 build.
// They are still strings, so a rename shows up only as a HarmonyX "Could not find method" in
// LogOutput.log, not as a build error — the per-method [AMPLITUDE] blocked log line below is the real
// proof a hook is live.
//
// Why all five: blocking LogEventAsync alone was not enough — a session's room_stats/perf_stats
// events still went out, and the LogEventAsync prefix never logged at all, so that entrypoint was
// never even called. Those events are the pre-serialized batch the client parks in the
// `pending_room_stats` PlayerPref (visible in the DUID-PROBE log), which points at
// LogSerializedEventAsync rather than LogEventAsync.
//
// Why the Log* prefixes alone STILL are not enough — and why `BlockAnalyticsUploadPatch` below is the
// part that actually stops the traffic: uploads to api2.amplitude.com kept showing up in mitmproxy
// with LogEventAsync/LogIdentifyAsync visibly blocked in LogOutput.log. The Log* methods only *queue*;
// the queue is persisted (`pending_room_stats`) and drained later by the client's own flush coroutines
// (Flush / AMEAMPDLJPN / PPOCFIHNKPP), which reach the network through the transport interface
// `FOMPBHDLPDO` — concrete impl `MHBPNDOGOLG` in RecNet.Runtime.dll, i.e. BestHTTP. So a batch queued
// in an earlier session ships on the next launch no matter what we do to the Log* doors. Blocking at
// the BestHTTP layer catches every path, present and future, and costs no obfuscated names.
[HarmonyPatch]
public static class AmplitudePatch
{
    private static readonly HashSet<string> _loggedBlocked = new();

    // Returns false to skip the original. Logs once per entrypoint so LogOutput.log shows which door
    // the client actually used.
    private static bool Block(string entrypoint)
    {
        if (_loggedBlocked.Add(entrypoint))
            Plugin.Log.LogInfo($"[AMPLITUDE] analytics disabled — blocked {entrypoint}");

        return false;
    }

    [HarmonyPrefix]
    [HarmonyPatch(typeof(AmplitudeAnalytics.AmplitudeAnalyticsClient), "LogEventAsync")]
    private static bool LogEventAsyncPrefix() =>
        Plugin.DisableTelemetry.Value && Block("LogEventAsync");

    [HarmonyPrefix]
    [HarmonyPatch(typeof(AmplitudeAnalytics.AmplitudeAnalyticsClient), "LogPrevSessionEventAsync")]
    private static bool LogPrevSessionEventAsyncPrefix() =>
        Plugin.DisableTelemetry.Value && Block("LogPrevSessionEventAsync");

    // The likely culprit for the room_stats/perf_stats batch — takes the already-serialized
    // Dictionary<string, object> that gets parked in `pending_room_stats`.
    [HarmonyPrefix]
    [HarmonyPatch(typeof(AmplitudeAnalytics.AmplitudeAnalyticsClient), "LogSerializedEventAsync")]
    private static bool LogSerializedEventAsyncPrefix() =>
        Plugin.DisableTelemetry.Value && Block("LogSerializedEventAsync");

    [HarmonyPrefix]
    [HarmonyPatch(typeof(AmplitudeAnalytics.AmplitudeAnalyticsClient), "LogIdentifyAsync")]
    private static bool LogIdentifyAsyncPrefix() =>
        Plugin.DisableTelemetry.Value && Block("LogIdentifyAsync");

    // The odd one out: static, and it returns a promise instead of void. Skipping it with a null
    // __result would hand the caller something it will chain .Then() on, so we substitute an
    // already-resolved promise — the call looks like it succeeded instantly. If we cannot build one,
    // we let the original run rather than risk a null-deref at quit time.
    [HarmonyPrefix]
    [HarmonyPatch(typeof(AmplitudeAnalytics.AmplitudeAnalyticsClient), "LogOutOfSessionEvent")]
    private static bool LogOutOfSessionEventPrefix(ref LAHBDKNMNHN __result)
    {
        if (!Plugin.DisableTelemetry.Value)
            return true;

        var resolved = ResolvedPromise();
        if (resolved == null)
            return true;

        __result = resolved;
        return Block("LogOutOfSessionEvent");
    }

    private static bool _promiseResolved;
    private static MethodInfo _resolvedPromiseGetter;

    // Finds the concrete Promise class's static `Resolved` property getter without hardcoding its
    // obfuscated name. Among the static, 0-param property getters in RecRoom.Promises.Runtime that
    // return the promise interface there are exactly two: the real (obfuscated) property getter and
    // the compiler-generated `get_<Name>_k__BackingField`. The backing field may be null if the
    // property initialises lazily, so we drop it by its compiler-generated name — which the
    // obfuscator leaves alone — and keep the other one.
    private static LAHBDKNMNHN ResolvedPromise()
    {
        if (!_promiseResolved)
        {
            _promiseResolved = true;

            var candidates = typeof(LAHBDKNMNHN).Assembly.GetTypes()
                .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
                .Where(m => m.ReturnType == typeof(LAHBDKNMNHN)
                            && m.GetParameters().Length == 0
                            && m.IsSpecialName
                            && !m.Name.EndsWith("_k__BackingField"))
                .ToList();

            if (candidates.Count == 1)
                _resolvedPromiseGetter = candidates[0];
            else
                Plugin.Log.LogWarning(
                    $"[AMPLITUDE] expected exactly one resolved-promise getter, found {candidates.Count} " +
                    "— LogOutOfSessionEvent will NOT be blocked");
        }

        if (_resolvedPromiseGetter == null)
            return null;

        return _resolvedPromiseGetter.Invoke(null, null) as LAHBDKNMNHN;
    }

    // Analytics hosts we refuse to talk to, matched two different ways because they identify
    // themselves two different ways:
    //
    //   AmplitudeDomains        — a registrable domain plus everything under it, so api2.amplitude.com
    //                             and api.eu.amplitude.com are both covered.
    //   CollectorLabelPrefixes  — the *first* hostname label, for the telemetry collector that lives
    //                             on whatever domain the deployment uses (for example, datacollection.example.net,
    //                             datacollection.rec.net, datacollection-eu.…). The domain varies, the
    //                             label doesn't, so match on the label and stay deployment-agnostic.
    //
    // Split into separate lists because they're *matched* differently, not configured differently —
    // one knob covers the lot.
    private static readonly string[] AmplitudeDomains = { "amplitude.com" };
    private static readonly string[] CollectorLabelPrefixes = { "datacollection" };

    // Backtrace and Unity's perf-events don't normally reach BestHTTP at all — Backtrace goes through
    // UnityWebRequest (see BacktracePatch) and Unity's is native (see UnityTelemetryPatch). They're
    // listed here anyway because it costs a string comparison to be right if that ever changes, and
    // because "the host block covers every host we don't want talked to" is easier to reason about
    // than a list with holes in it. Only perf-events is named, not all of cloud.unity3d.com — the
    // client uses other Unity services.
    private static readonly string[] BacktraceDomains = { "backtrace.io" };
    private static readonly string[] UnityTelemetryHosts = { "perf-events.cloud.unity3d.com" };

    private static bool IsUnderAnyDomain(string host, string[] domains) =>
        domains.Any(d => host.Equals(d, StringComparison.OrdinalIgnoreCase)
                         || host.EndsWith("." + d, StringComparison.OrdinalIgnoreCase));

    private static bool IsAmplitudeHost(string host) => IsUnderAnyDomain(host, AmplitudeDomains);

    private static bool IsCollectorHost(string host)
    {
        var dot = host.IndexOf('.');
        var firstLabel = dot < 0 ? host : host.Substring(0, dot);

        return CollectorLabelPrefixes.Any(p => firstLabel.StartsWith(p, StringComparison.OrdinalIgnoreCase));
    }

    // One knob for the lot. The vendors are split into separate lists above because they're matched
    // differently, not because they're configured differently.
    private static bool IsBlockedHost(string host)
    {
        if (string.IsNullOrEmpty(host) || !Plugin.DisableTelemetry.Value)
            return false;

        return IsAmplitudeHost(host)
               || IsCollectorHost(host)
               || IsUnderAnyDomain(host, BacktraceDomains)
               || UnityTelemetryHosts.Any(h => host.Equals(h, StringComparison.OrdinalIgnoreCase));
    }

    // The part that actually stops the traffic — see the note at the top of the file. Prefixes the
    // same BestHTTP entrypoint SendRequestPatch hooks (HTTPManager is BestHTTP's own type, so no
    // obfuscated names are involved and this survives game upgrades) and, for analytics hosts, hands
    // the caller a synthetic 200 instead of sending anything.
    //
    // Faking success rather than failure is deliberate: the transport resolves its promise, the flush
    // coroutine considers the batch delivered, and the client clears `pending_room_stats` — so nothing
    // accumulates and nothing retries. Failing the request instead would leave the batch queued and
    // re-attempted every session.
    [HarmonyPatch(typeof(HTTPManager), "SendRequest", [typeof(HTTPRequest)])]
    public static class BlockAnalyticsUploadPatch
    {
        private static bool Prefix(HTTPRequest request, ref HTTPRequest __result)
        {
            // SendRequest returns the request it was handed; callers chain off it, so hand it back
            // even though we never send it.
            __result = request;

            return !Drop(request);
        }

        // Second net, one layer down. Every SendRequest overload funnels into SendRequestImpl, and
        // IL2CPP is free to inline the tiny SendRequest(HTTPRequest) body into its callers — a hook on
        // it then never fires for those call sites (gotcha: a Harmony patch that loads clean can still
        // never run). SendRequestImpl is the last managed-visible chokepoint before the connection, so
        // anything that slipped past the hook above is caught here.
        [HarmonyPatch(typeof(HTTPManager), "SendRequestImpl", [typeof(HTTPRequest)])]
        public static class ImplPatch
        {
            private static bool Prefix(HTTPRequest request) => !Drop(request);
        }

        // True when the request was blocked (caller should skip the original).
        private static bool Drop(HTTPRequest request)
        {
            if (!IsBlockedHost(request.Uri.Host))
                return false;

            // Once per host normally; every request under [Advanced] Debug, since "did this specific
            // upload get dropped or did it slip past?" is exactly the question a mitmproxy trace
            // raises, and a deduped line can't answer it.
            if (Plugin.Debug.Value)
                Plugin.Log.LogInfo($"[ANALYTICS] dropped {request.MethodType} {request.Uri.AbsoluteUri}");
            else if (_loggedBlocked.Add("upload:" + request.Uri.Host))
                Plugin.Log.LogInfo($"[ANALYTICS] dropping uploads to {request.Uri.Host}");

            try
            {
                CompleteWithFakeSuccess(request);
            }
            catch (Exception e)
            {
                // Couldn't synthesize the response — still don't send. The request's callback never
                // fires, so whatever promise the transport made stays pending; that's a stalled flush
                // coroutine at worst, versus telemetry leaving the box.
                Plugin.Log.LogWarning($"[ANALYTICS] blocked {request.Uri.Host} but could not fake a response: {e.Message}");
            }

            return true;
        }

        private static void CompleteWithFakeSuccess(HTTPRequest request)
        {
            var body = FakeBodyFor(request);

            var response = new HTTPResponse(request, new Il2CppSystem.IO.MemoryStream(), false, false)
            {
                StatusCode = 200,
                Message = "OK",
                Data = new Il2CppStructArray<byte>(Encoding.UTF8.GetBytes(body)),
            };

            request.Response = response;
            request.State = HTTPRequestStates.Finished;

            // BestHTTP would normally fire this from HTTPManager's update loop a frame or more later.
            // Firing it inline is safe here because the callback is assigned before SendRequest is
            // called, and the promise it resolves already exists by then.
            request.Callback?.Invoke(request, response);
        }

        // Whatever the endpoint would have said on a good day. Amplitude's real shapes are known:
        // /identify answers with the literal "success", the v2 batch endpoint with a small JSON
        // envelope. The collector's shape isn't known, so we fall back to `{"success":true}` — the
        // envelope every first-party RecNet endpoint uses (it's what the real deviceId endpoint
        // returns) and a far better guess than an empty body,
        // which the RecNet HTTP wrapper rejects outright with "Response was empty".
        private static string FakeBodyFor(HTTPRequest request)
        {
            if (!IsAmplitudeHost(request.Uri.Host))
                return "{\"success\":true}";

            return request.Uri.AbsoluteUri.Contains("/identify", StringComparison.OrdinalIgnoreCase)
                ? "success"
                : "{\"code\":200,\"events_ingested\":0,\"payload_size_bytes\":0,\"server_upload_time\":"
                  + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + "}";
        }
    }
}
