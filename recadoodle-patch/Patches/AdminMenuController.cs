using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Il2CppInterop.Runtime.Attributes;
using UnityEngine;

namespace Recadoodle.Patches;

public sealed class AdminMenuController : MonoBehaviour
{
    private static readonly HttpClient Client = new();
    private bool _visible;
    private Rect _window = new(30, 50, 520, 480);
    private int _tab;
    private string _accountId = "2";
    private string _message = "";
    private string _gift = "";
    private string _giftMessage = "";
    private string _giftType = "avatar";
    private string _quantity = "1";
    private string _announcement = "Server restarting in 5 minutes";
    private string _sound = "warning";
    private string _banner = "";
    private int _announcementId;
    private float _nextPoll;
    private bool _polling;
    private string _pendingSound = "";
    private string _status = "Press Refresh to check the server.";

    public AdminMenuController(IntPtr pointer) : base(pointer) { }

    private void Update()
    {
        if (Plugin.EnableAdminMenu.Value && Input.GetKeyDown(KeyCode.F8))
            _visible = !_visible;
        if (!_polling && Time.unscaledTime >= _nextPoll && !string.IsNullOrEmpty(SendRequestPatch.BearerToken))
        {
            _nextPoll = Time.unscaledTime + 4f;
            _ = PollAnnouncement();
        }
        if (!string.IsNullOrEmpty(_pendingSound))
        {
            PlaySound(_pendingSound);
            _pendingSound = "";
        }
    }

    private void OnGUI()
    {
        var previous = GUI.backgroundColor;
        GUI.backgroundColor = MenuColor();
        if (_visible)
            _window = GUI.Window(3121, _window, (GUI.WindowFunction)DrawWindow, "Recadoodle Admin");
        if (!string.IsNullOrEmpty(_banner))
            GUI.Box(new Rect(Screen.width / 2f - 300, 24, 600, 54), _banner);
        GUI.backgroundColor = previous;
    }

    private void DrawWindow(int id)
    {
        GUI.Box(new Rect(12, 28, 496, 55), _status);
        var tabs = new[] { "Dashboard", "Messages", "Gifts", "Broadcast", "Theme" };
        for (var i = 0; i < tabs.Length; i++)
            if (GUI.Button(new Rect(12 + i * 99, 91, 94, 32), tabs[i])) _tab = i;
        GUI.Box(new Rect(12, 132, 496, 300), "");
        if (_tab == 0) DrawDashboard();
        else if (_tab == 1) DrawMessages();
        else if (_tab == 2) DrawGifts();
        else if (_tab == 3) DrawBroadcast();
        else DrawTheme();
        GUI.Label(new Rect(16, 442, 480, 24), "F8 closes • authenticated as the signed-in developer");
        GUI.DragWindow(new Rect(0, 0, 520, 25));
    }

    private void DrawDashboard()
    {
        GUI.Label(new Rect(30, 155, 440, 30), "SERVER OVERVIEW");
        if (GUI.Button(new Rect(30, 200, 180, 38), "Refresh server status")) _ = Request("GET", "/api/recadoodle/admin/status", null);
        GUI.Label(new Rect(30, 255, 430, 50), "Live player, room and account totals appear in the status card above.");
    }

    private void DrawMessages()
    {
        GUI.Label(new Rect(30, 155, 100, 24), "Account ID"); _accountId = GUI.TextField(new Rect(140, 151, 140, 30), _accountId, 12);
        GUI.Label(new Rect(30, 198, 100, 24), "Message"); _message = GUI.TextArea(new Rect(140, 194, 335, 90), _message, 500);
        if (GUI.Button(new Rect(140, 300, 190, 38), "Send as Coach")) _ = Request("POST", "/api/recadoodle/admin/coach-message", $"{{\"accountId\":\"{Escape(_accountId)}\",\"message\":\"{Escape(_message)}\"}}");
    }

    private void DrawGifts()
    {
        GUI.Label(new Rect(30, 153, 100, 24), "Account ID"); _accountId = GUI.TextField(new Rect(140, 149, 140, 30), _accountId, 12);
        GUI.Label(new Rect(30, 193, 100, 24), "Item name"); _gift = GUI.TextField(new Rect(140, 189, 335, 30), _gift, 255);
        if (GUI.Button(new Rect(140, 229, 145, 30), "Type: " + _giftType)) _giftType = _giftType == "avatar" ? "consumable" : _giftType == "consumable" ? "equipment" : "avatar";
        GUI.Label(new Rect(300, 234, 55, 24), "Qty"); _quantity = GUI.TextField(new Rect(355, 229, 70, 30), _quantity, 4);
        GUI.Label(new Rect(30, 275, 100, 24), "Gift note"); _giftMessage = GUI.TextField(new Rect(140, 271, 335, 30), _giftMessage, 500);
        if (GUI.Button(new Rect(140, 318, 190, 38), "Send gift")) _ = Request("POST", "/api/recadoodle/admin/gift", $"{{\"accountId\":\"{Escape(_accountId)}\",\"description\":\"{Escape(_gift)}\",\"type\":\"{_giftType}\",\"quantity\":\"{Escape(_quantity)}\",\"message\":\"{Escape(_giftMessage)}\"}}");
    }

    private void DrawBroadcast()
    {
        GUI.Label(new Rect(30, 155, 440, 24), "SERVER-WIDE ANNOUNCEMENT"); _announcement = GUI.TextArea(new Rect(30, 190, 445, 85), _announcement, 500);
        if (GUI.Button(new Rect(30, 290, 170, 32), "Sound: " + _sound)) _sound = _sound == "none" ? "notification" : _sound == "notification" ? "warning" : "none";
        if (GUI.Button(new Rect(215, 290, 220, 38), "Broadcast to everyone")) _ = Request("POST", "/api/recadoodle/admin/announcement", $"{{\"message\":\"{Escape(_announcement)}\",\"sound\":\"{_sound}\"}}");
    }

    private void DrawTheme()
    {
        GUI.Label(new Rect(30, 155, 440, 24), "LIVE APPEARANCE");
        if (GUI.Button(new Rect(30, 195, 210, 38), "Watch accent: " + Plugin.WatchAccentColor.Value)) Plugin.WatchAccentColor.Value = Next(Plugin.WatchAccentColor.Value, new[] { "Orange", "Blue", "Purple", "Green", "Red", "Pink" });
        if (GUI.Button(new Rect(255, 195, 220, 38), "Watch background: " + Plugin.WatchBackgroundColor.Value)) Plugin.WatchBackgroundColor.Value = Next(Plugin.WatchBackgroundColor.Value, new[] { "Charcoal", "Navy", "Slate", "Purple", "Black" });
        if (GUI.Button(new Rect(30, 250, 210, 38), "Menu colour: " + Plugin.AdminMenuColor.Value)) Plugin.AdminMenuColor.Value = Next(Plugin.AdminMenuColor.Value, new[] { "Blue", "Orange", "Purple", "Green", "Red", "Gray" });
    }

    [HideFromIl2Cpp]
    private async Task Request(string method, string path, string body)
    {
        var token = SendRequestPatch.BearerToken;
        if (string.IsNullOrEmpty(token)) { _status = "Log in first so the menu can authenticate."; return; }
        try
        {
            using var request = new HttpRequestMessage(new HttpMethod(method), Plugin.ServerHostname.Value.TrimEnd('/') + path);
            request.Headers.TryAddWithoutValidation("Authorization", token);
            if (body != null) request.Content = new StringContent(body, Encoding.UTF8, "application/json");
            using var response = await Client.SendAsync(request);
            _status = $"{(int)response.StatusCode}: {await response.Content.ReadAsStringAsync()}";
        }
        catch (Exception exception) { _status = "Request failed: " + exception.Message; }
    }

    private static string Escape(string value) => value.Replace("\\", "\\\\").Replace("\"", "\\\"");

    private static string Next(string current, string[] choices)
    {
        var index = Array.IndexOf(choices, current);
        return choices[(index + 1) % choices.Length];
    }

    private static Color MenuColor() => Plugin.AdminMenuColor.Value switch
    {
        "Orange" => new Color(1f, 0.30f, 0.055f), "Purple" => new Color(0.58f, 0.28f, 1f),
        "Green" => new Color(0.10f, 0.75f, 0.42f), "Red" => new Color(0.95f, 0.18f, 0.22f),
        "Gray" => new Color(0.45f, 0.48f, 0.52f), _ => new Color(0.10f, 0.48f, 1f),
    };

    [HideFromIl2Cpp]
    private async Task PollAnnouncement()
    {
        _polling = true;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, Plugin.ServerHostname.Value.TrimEnd('/') + "/api/recadoodle/announcements/latest");
            request.Headers.TryAddWithoutValidation("Authorization", SendRequestPatch.BearerToken);
            using var response = await Client.SendAsync(request);
            if (!response.IsSuccessStatusCode) return;
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var value = json.RootElement.GetProperty("announcement");
            if (value.ValueKind == JsonValueKind.Null) { _banner = ""; return; }
            var id = value.GetProperty("id").GetInt32();
            _banner = value.GetProperty("message").GetString() ?? "";
            if (id != _announcementId) { _announcementId = id; _pendingSound = value.GetProperty("sound").GetString() ?? ""; }
        }
        catch (Exception exception) { Plugin.Log.LogWarning("[ADMIN] announcement poll failed: " + exception.Message); }
        finally { _polling = false; }
    }

    private static void PlaySound(string sound)
    {
        if (sound == "none") return;
        foreach (var clip in Resources.FindObjectsOfTypeAll<AudioClip>())
        {
            if (clip != null && clip.name.IndexOf(sound == "warning" ? "alert" : "notification", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                AudioSource.PlayClipAtPoint(clip, Camera.main != null ? Camera.main.transform.position : Vector3.zero);
                return;
            }
        }
    }
}
