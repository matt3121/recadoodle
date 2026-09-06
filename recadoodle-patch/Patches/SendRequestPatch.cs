using System;
using BestHTTP;
using HarmonyLib;
using Il2CppInterop.Runtime;

namespace Recadoodle.Patches;

/**
    Intercept a variety of HTTP requests and rewrite them to point to our own custom server.
 */
public class SendRequestPatch
{
    internal static string BearerToken { get; private set; } = "";
    private static bool _loggedTokenCapture;
    // Official name server host to redirect away from, swapped for the custom server.
    private const string OfficialNameServer = "ns.rec.net";

    // Skip when HTTP-logging so we don't spam the logs.
    private static readonly string[] LogIgnoreSubstrings =
    {
        "/api/gamesight/event",
        "/data/heartbeat",
        "/identify",
        "/httpapi",
        "/data/event",
    };

    private static bool IsIgnoredForLogging(string url)
    {
        foreach (var s in LogIgnoreSubstrings)
            if (url.Contains(s, StringComparison.OrdinalIgnoreCase))
                return true;
        return false;
    }

    // Cap logged bodies so a large response/request doesn't flood the log.
    private const int MaxLoggedBodyLength = 10000;

    private static string Truncate(string s)
    {
        if (string.IsNullOrEmpty(s) || s.Length <= MaxLoggedBodyLength)
            return s;
        return s.Substring(0, MaxLoggedBodyLength) + $"... <truncated {s.Length - MaxLoggedBodyLength} chars>";
    }

    [HarmonyPatch(typeof(HTTPManager), "SendRequest", [typeof(HTTPRequest)])]
    public class ConnectToRecNetPatch
    {
        private static void Prefix(ref HTTPRequest request)
        {
            var authorization = request.GetFirstHeaderValue("authorization");
            if (!string.IsNullOrWhiteSpace(authorization) && authorization.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
            {
                BearerToken = authorization;
                if (!_loggedTokenCapture)
                {
                    _loggedTokenCapture = true;
                    Plugin.Log.LogInfo("[ADMIN] Captured the signed-in game token.");
                }
            }
            var debug = Plugin.Debug.Value && !IsIgnoredForLogging(request.Uri.AbsoluteUri);

            if (debug)
            {
                var entityBody = request.GetEntityBody();
                string body;
                if (entityBody == null)
                    body = "<none>";
                else if (IsBinaryContentType(request.GetFirstHeaderValue("content-type")) || LooksBinary(entityBody))
                    body = BinaryPreview(entityBody);
                else
                    body = System.Text.Encoding.UTF8.GetString(entityBody);
                Plugin.Log.LogInfo($"[HTTP] {request.MethodType} {request.Uri.AbsoluteUri} body={Truncate(body)}");
            }

            var host = request.Uri.Host;
            if (host == OfficialNameServer)
            {
                // Carry the configured scheme and port too. Host-only replacement turns a local
                // target such as http://localhost:5050 into https://localhost:443.
                var configuredServer = new System.Uri(Plugin.ServerHostname.Value);
                var builder = new Il2CppSystem.UriBuilder(request.Uri)
                {
                    Scheme = configuredServer.Scheme,
                    Host = configuredServer.Host,
                    Port = configuredServer.Port,
                };
                request.Uri = builder.Uri;

                if (debug)
                    Plugin.Log.LogInfo($"[HTTP] intercepted {host} -> {configuredServer.Authority}");
            }

            if (debug)
                LogResponseWhenDone(request);
        }
    }

    // Wraps the request's completion callback so we log the response (status + body) when it
    // finishes, then forwards to the game's original callback. This is how we see *which*
    // request comes back empty (RecNet throws "Response was empty" on a blank body).
    private static void LogResponseWhenDone(HTTPRequest request)
    {
        try
        {
            var original = request.Callback;
            var url = request.Uri.AbsoluteUri;

            request.Callback = DelegateSupport.ConvertDelegate<OnRequestFinishedDelegate>(
                (Action<HTTPRequest, HTTPResponse>)((req, resp) =>
                {
                    if (resp == null)
                        Plugin.Log.LogWarning($"[HTTP] <- {url} NO RESPONSE (state={req.State})");
                    else
                    {
                        string text;
                        if (IsBinaryContentType(resp.GetFirstHeaderValue("content-type")))
                            text = "<binary>";
                        else
                        {
                            text = resp.DataAsText;
                            if (string.IsNullOrEmpty(text)) text = "<empty>";
                        }
                        var msg = $"[HTTP] <- {resp.StatusCode} {url} body={Truncate(text)}";
                        if (resp.StatusCode is >= 200 and < 300)
                            Plugin.Log.LogInfo(msg);
                        else
                            Plugin.Log.LogError(msg);
                    }

                    original?.Invoke(req, resp);
                }));
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[HTTP] failed to attach response logger: {e}");
        }
    }

    // Content-Type prefixes/keywords we treat as textual; anything else is logged as <binary> so we
    // don't dump image/asset bytes into the log.
    private static readonly string[] TextContentTypes =
    {
        "text/", "application/json", "application/xml", "application/javascript",
        "application/x-www-form-urlencoded", "+json", "+xml",
    };

    // True if the body is (probably) binary and shouldn't be logged as text. Defaults to text when
    // there's no Content-Type, so we err toward logging rather than hiding.
    private static bool IsBinaryContentType(string contentType)
    {
        if (string.IsNullOrEmpty(contentType)) return false;

        foreach (var t in TextContentTypes)
            if (contentType.Contains(t, StringComparison.OrdinalIgnoreCase))
                return false;
        return true;
    }

    // Render the leading bytes of a binary body as text so structured framing (e.g. multipart form
    // boundaries and part headers) stays readable, while raw bytes are shown as \xNN escapes. Capped
    // at MaxLoggedBodyLength since the interesting framing is at the front.
    private static string BinaryPreview(byte[] data)
    {
        if (data.Length == 0) return "<binary empty>";

        var sb = new System.Text.StringBuilder(MaxLoggedBodyLength + 32);
        sb.Append("<binary ").Append(data.Length).Append(" bytes> ");
        var i = 0;
        // Cap on rendered length, not byte count: escapes expand a byte to 4 chars, so this keeps the
        // preview near MaxLoggedBodyLength and avoids a second pass by Truncate at the log site.
        for (; i < data.Length && sb.Length < MaxLoggedBodyLength; i++)
        {
            var b = data[i];
            if (b == 0x09 || b == 0x0A || b == 0x0D || (b >= 0x20 && b < 0x7F))
                sb.Append((char)b);
            else
                sb.Append("\\x").Append(b.ToString("x2"));
        }
        if (i < data.Length)
            sb.Append($"... <truncated {data.Length - i} bytes>");
        return sb.ToString();
    }

    // Content sniff for raw request bytes — the Content-Type header isn't reliably set at
    // SendRequest time (e.g. multipart form bodies set it lazily, and the body still embeds the
    // raw image), so look at the bytes: a NUL byte, or a high ratio of non-text control bytes in
    // the first chunk, means it's binary (or binary-mixed like a multipart upload).
    private static bool LooksBinary(byte[] data)
    {
        if (data.Length == 0) return false;

        var sample = Math.Min(data.Length, 4096);
        var nonText = 0;
        for (var i = 0; i < sample; i++)
        {
            var b = data[i];
            if (b == 0) return true;
            // Control chars other than tab/newline/carriage-return.
            if (b < 0x20 && b != 0x09 && b != 0x0A && b != 0x0D) nonText++;
        }
        return nonText * 100 / sample > 10;
    }
}
