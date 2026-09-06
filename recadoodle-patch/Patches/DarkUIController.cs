using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Recadoodle.Patches;

/// <summary>Applies a dark palette only to Watch and RRUI hierarchies.</summary>
public sealed class DarkUIController : MonoBehaviour
{
    private static readonly Color LightText = new(0.94f, 0.93f, 0.91f, 1f);
    private static readonly Color MutedText = new(0.72f, 0.72f, 0.70f, 1f);
    private float _nextScan;

    public DarkUIController(IntPtr pointer) : base(pointer) { }

    private void Update()
    {
        if (!Plugin.EnableDarkUI.Value || Time.unscaledTime < _nextScan)
            return;
        _nextScan = Time.unscaledTime + 1.5f;
        ApplyImages();
        ApplyText();
    }

    private static bool IsWatchObject(Component component)
    {
        var current = component.transform;
        for (var depth = 0; current != null && depth < 14; depth++, current = current.parent)
        {
            var name = current.name ?? string.Empty;
            if (name.IndexOf("watch", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("rrui", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("login", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("accountpicker", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("account picker", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("authentication", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
        }
        return false;
    }

    private static bool IsOrange(Color color) =>
        color.r > 0.65f && color.r > color.g * 1.35f && color.g > color.b * 1.25f;

    private static bool IsAccent(Color color) => IsOrange(color) ||
        (Math.Max(color.r, Math.Max(color.g, color.b)) - Math.Min(color.r, Math.Min(color.g, color.b)) > 0.35f &&
         Math.Max(color.r, Math.Max(color.g, color.b)) > 0.55f);

    internal static Color Accent => Plugin.WatchAccentColor.Value switch
    {
        "Blue" => new Color(0.10f, 0.48f, 1f, 1f), "Purple" => new Color(0.58f, 0.28f, 1f, 1f),
        "Green" => new Color(0.10f, 0.75f, 0.42f, 1f), "Red" => new Color(0.95f, 0.18f, 0.22f, 1f),
        "Pink" => new Color(1f, 0.22f, 0.58f, 1f), _ => new Color(1f, 0.30f, 0.055f, 1f),
    };

    private static Color Panel => Plugin.WatchBackgroundColor.Value switch
    {
        "Navy" => new Color(0.035f, 0.07f, 0.14f, 0.98f), "Slate" => new Color(0.10f, 0.13f, 0.18f, 0.98f),
        "Purple" => new Color(0.10f, 0.055f, 0.15f, 0.98f), "Black" => new Color(0.015f, 0.015f, 0.02f, 0.98f),
        _ => new Color(0.055f, 0.063f, 0.075f, 0.98f),
    };

    private static Color Raised => Color.Lerp(Panel, Color.white, 0.08f);

    private static bool Near(Color color, float r, float g, float b) =>
        Math.Abs(color.r - r) < 0.035f && Math.Abs(color.g - g) < 0.035f && Math.Abs(color.b - b) < 0.035f;

    private static bool IsKnownPanel(Color color) => Near(color, 0.055f, 0.063f, 0.075f) ||
        Near(color, 0.035f, 0.07f, 0.14f) || Near(color, 0.10f, 0.13f, 0.18f) ||
        Near(color, 0.10f, 0.055f, 0.15f) || Near(color, 0.015f, 0.015f, 0.02f);

    private static void ApplyImages()
    {
        foreach (var image in Resources.FindObjectsOfTypeAll<Image>())
        {
            if (image == null || !IsWatchObject(image) || image.color.a < 0.08f)
                continue;
            var color = image.color;
            if (IsAccent(color))
                image.color = new Color(Accent.r, Accent.g, Accent.b, color.a);
            else if (IsKnownPanel(color))
                image.color = new Color(Panel.r, Panel.g, Panel.b, color.a);
            else if (color.r + color.g + color.b > 1.55f)
                image.color = new Color(Raised.r, Raised.g, Raised.b, color.a);
            else if (color.r + color.g + color.b > 0.35f)
                image.color = new Color(Panel.r, Panel.g, Panel.b, color.a);
        }
    }

    private static void ApplyText()
    {
        foreach (var label in Resources.FindObjectsOfTypeAll<TMP_Text>())
        {
            if (label == null || !IsWatchObject(label))
                continue;
            label.color = IsAccent(label.color) ? Accent :
                (label.color.a < 0.7f ? MutedText : LightText);
        }
        foreach (var label in Resources.FindObjectsOfTypeAll<Text>())
        {
            if (label == null || !IsWatchObject(label))
                continue;
            label.color = IsAccent(label.color) ? Accent :
                (label.color.a < 0.7f ? MutedText : LightText);
        }
    }
}
