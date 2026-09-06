using System;

namespace Recadoodle.Patches;

// Unity's own telemetry — the uploads to perf-events.cloud.unity3d.com.
//
// !! THIS DOES NOT WORK on the 20230414 build, and that is a known, accepted limitation — don't spend
// another afternoon on it. Confirmed at runtime: the setters below are refused, `enabled` reads back
// True on all five attempts, and perf-events uploads keep flowing. It's left in because it costs
// nothing, is the correct thing to do if a future build stops refusing, and the read-back logs the
// truth either way rather than pretending. The parts of `Disable Telemetry` that carry the actual win
// are Amplitude, the collector and Backtrace — all confirmed dropping — and they take out the bulk of
// the noise. If perf-events ever has to go for real, it needs a hosts-file/DNS block or a native hook;
// there is no managed lever.
//
// There is nothing to hook here, and that's the point: `UnityEngine.Analytics.Analytics` and
// `PerformanceReporting` are thin managed shims over native engine code, and the uploads happen inside
// the player, not on any managed send path a Harmony prefix could sit on. Blocking this one at the HTTP
// layer is equally hopeless — it never touches BestHTTP or UnityWebRequest. What it *does* have is a
// documented opt-out, so we flip the switches at startup and read them back.
//
// Performance Reporting is the exception/crash reporter, Analytics is the event stream; both feed
// perf-events, so both go off. `limitUserTracking` and `deviceStatsEnabled` cover the case where
// something re-enables the event stream behind our back — with those set, what it can collect is
// nothing worth sending.
internal static class UnityTelemetryPatch
{
    // Applied from Plugin.Load and again on each scene load until it sticks — these are native
    // properties whose setters can be refused (service not initialised yet, build flags), so
    // "set it once at load and assume" is exactly how this silently does nothing.
    private const int MaxAttempts = 5;

    private static bool _done;
    private static int _attempts;

    public static void Apply()
    {
        if (_done || !Plugin.DisableTelemetry.Value || _attempts >= MaxAttempts)
            return;

        _attempts++;

        try
        {
            UnityEngine.Analytics.PerformanceReporting.enabled = false;
            UnityEngine.Analytics.Analytics.enabled = false;
            UnityEngine.Analytics.Analytics.deviceStatsEnabled = false;
            UnityEngine.Analytics.Analytics.limitUserTracking = true;
        }
        catch (Exception e)
        {
            // No _done: a later scene load gets another go, up to MaxAttempts.
            if (_attempts >= MaxAttempts)
                Plugin.Log.LogWarning($"[UNITY-TELEMETRY] gave up flipping the opt-out switches after {_attempts} attempts: {e.Message}");
            return;
        }

        // The read-back is the proof, not the assignment above. A refused setter is silent.
        var perf = UnityEngine.Analytics.PerformanceReporting.enabled;
        var analytics = UnityEngine.Analytics.Analytics.enabled;

        _done = !perf && !analytics;

        if (_done)
            Plugin.Log.LogInfo(
                $"[UNITY-TELEMETRY] disabled — PerformanceReporting.enabled={perf} Analytics.enabled={analytics} " +
                $"deviceStats={UnityEngine.Analytics.Analytics.deviceStatsEnabled} " +
                $"limitUserTracking={UnityEngine.Analytics.Analytics.limitUserTracking}");
        else if (_attempts >= MaxAttempts)
            // Info, not a warning: this is the known outcome on this build (see the header), not a
            // fault to go chasing. It stays logged so a build that *does* accept the switches is
            // visible as a change rather than a surprise.
            Plugin.Log.LogInfo(
                $"[UNITY-TELEMETRY] switches refused after {_attempts} attempts — " +
                $"PerformanceReporting.enabled={perf} Analytics.enabled={analytics}. " +
                "Known limitation: perf-events.cloud.unity3d.com uploads continue. The rest of Disable Telemetry is unaffected.");
    }
}
