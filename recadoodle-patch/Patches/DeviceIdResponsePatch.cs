using System;
using System.Text;
using BestHTTP;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace Recadoodle.Patches;

// Experiment harness for the Create Account hang.
//
// On a device-id mismatch the client POSTs PlayerReporting/v1/deviceId, the server answers
// 200 {"success":true}, and then the client stops: CheatManager.WriteDUIDs() is never called, so the
// new id is never persisted and the flow never reaches create_account. That means the client can't
// proceed on what it got back.
//
// This rewrites that one response body before the game sees it, so response shapes can be tried
// without redeploying the server. WriteDUIDs() appearing in the log (see DUIDProbePatch) is the
// pass signal: it means the client accepted the response and resumed the migration.
[HarmonyPatch]
public static class DeviceIdResponsePatch
{
    private const string Endpoint = "/PlayerReporting/v1/deviceId";

    [HarmonyPrefix]
    [HarmonyPatch(typeof(HTTPManager), "SendRequest", [typeof(HTTPRequest)])]
    private static void Prefix(HTTPRequest request)
    {
        if (!request.Uri.AbsoluteUri.Contains(Endpoint, StringComparison.OrdinalIgnoreCase))
            return;

        var original = request.Callback;

        // Whether the game attached a completion callback at all. If this logs False, the client is
        // not waiting on this request through the callback API and the "stuck on the response" model
        // is wrong -- that would be worth knowing before chasing response shapes any further.
        Plugin.Log.LogWarning($"[DEVICEID] request seen; game callback attached = {original != null}");

        var body = Plugin.DeviceIdResponseOverride.Value;
        if (string.IsNullOrEmpty(body))
            return;

        var status = Plugin.DeviceIdResponseStatus.Value;

        request.Callback = DelegateSupport.ConvertDelegate<OnRequestFinishedDelegate>(
            (Action<HTTPRequest, HTTPResponse>)((req, resp) =>
            {
                if (resp != null)
                {
                    // Set both: DataAsText is computed from Data but cached in dataAsText once read,
                    // and our own HTTP logger may already have read it.
                    resp.Data = new Il2CppStructArray<byte>(Encoding.UTF8.GetBytes(body));
                    resp.dataAsText = body;
                    resp.StatusCode = status;
                    Plugin.Log.LogWarning($"[DEVICEID] response overridden -> {status} {body}");
                }

                original?.Invoke(req, resp);
            }));
    }
}
