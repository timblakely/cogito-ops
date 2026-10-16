// Exercise the real Wolf packet handler and Wayland event output without a GPU
// or uinput: record events at the same GStreamer boundary as the compositor.
#include <control/input_handler.hpp>
#include <core/virtual-display.hpp>
#include <linux/input-event-codes.h>
#include <iostream>
#include <set>
#include <stdexcept>
#include <tuple>
#include <vector>

using namespace wolf::core;
using namespace moonlight::control::pkts;

struct Recorder {
  std::set<unsigned int> down;
  std::vector<std::pair<unsigned int, bool>> keys;
  std::vector<std::set<unsigned int>> clicks;
};

static gboolean record_event(GstElement *element, GstEvent *event) {
  auto &r = *static_cast<Recorder *>(g_object_get_data(G_OBJECT(element), "recorder"));
  auto s = gst_event_get_structure(event);
  gboolean pressed = false;
  if (s && gst_structure_get_boolean(s, "pressed", &pressed)) {
    guint key = 0;
    if (gst_structure_has_name(s, "KeyboardKey") && gst_structure_get_uint(s, "key", &key)) {
      r.keys.emplace_back(key, pressed);
      if (pressed) r.down.insert(key);
      else r.down.erase(key);
    } else if (gst_structure_has_name(s, "MouseButton") && pressed) {
      r.clicks.push_back(r.down);
    }
  }
  gst_event_unref(event);
  return TRUE;
}

static void require(bool ok, const char *message) {
  if (!ok) throw std::runtime_error(message);
}

static void key(events::StreamSession &session, short code, char modifiers, INPUT_TYPE type = KEY_PRESS) {
  KEYBOARD_PACKET p{};
  p.type = type;
  p.key_code = boost::endian::native_to_little(static_cast<short>(code | 0x8000));
  p.modifiers = modifiers;
  control::keyboard_key(p, session);
}

int main() {
  gst_init(nullptr, nullptr);
  auto type = g_type_register_static_simple(
      GST_TYPE_ELEMENT, "WolfInputRecorder", sizeof(GstElementClass),
      [](gpointer klass, gpointer) { GST_ELEMENT_CLASS(klass)->send_event = record_event; },
      sizeof(GstElement), nullptr, GTypeFlags(0));
  Recorder recorder;
  auto element = gstreamer::gst_element_ptr(
      GST_ELEMENT(g_object_new(type, nullptr)), [](GstElement *e) { gst_object_unref(e); });
  g_object_set_data(G_OBJECT(element.get()), "recorder", &recorder);
  auto display = virtual_display::create_wayland_display(element, "test");
  events::StreamSession session{};
  session.keyboard->emplace(std::in_place_type<virtual_display::WaylandKeyboard>, display);
  session.mouse->emplace(std::in_place_type<virtual_display::WaylandMouse>, display);

  try {
    for (auto [code, bit, linux_code] : {
             std::tuple<short, char, unsigned>{M_CTRL, CTRL, KEY_LEFTCTRL},
             {M_LCTRL, CTRL, KEY_LEFTCTRL}, {M_RCTRL, CTRL, KEY_RIGHTCTRL},
             {M_SHIFT, SHIFT, KEY_LEFTSHIFT}, {M_LSHIFT, SHIFT, KEY_LEFTSHIFT},
             {M_RSHIFT, SHIFT, KEY_RIGHTSHIFT}, {M_ALT, ALT, KEY_LEFTALT},
             {M_RALT, ALT, KEY_RIGHTALT}, {M_META, META, KEY_LEFTMETA},
             {M_RMETA, META, KEY_RIGHTMETA}}) {
      recorder.keys.clear();
      recorder.clicks.clear();
      key(session, code, bit);
      require(recorder.down.contains(linux_code), "Modifier was released immediately after key-down");
      key(session, 0x41, bit); // Other keys must not release the held modifier.
      key(session, 0x41, bit, KEY_RELEASE);
      require(recorder.down.contains(linux_code), "Letter key released a physically held modifier");
      for (unsigned char button : {1, 3}) {
        MOUSE_BUTTON_PACKET p{};
        p.type = MOUSE_BUTTON_PRESS;
        p.button = button;
        control::mouse_button(p, session);
        p.type = MOUSE_BUTTON_RELEASE;
        control::mouse_button(p, session);
      }
      require(recorder.clicks.size() == 2, "Missing left/right click events");
      for (auto &click : recorder.clicks)
        require(click.contains(linux_code), "Click did not retain its modifier");
      key(session, code, NONE, KEY_RELEASE);
      require(recorder.down.empty(), "Modifier remained stuck after key-up");
      require(recorder.keys.size() == 4, "Unexpected synthetic modifier press/release");
    }

    // A packet flag without a physical key-down must still synthesize Ctrl+A.
    recorder.keys.clear();
    key(session, 0x41, CTRL);
    require(recorder.keys == std::vector<std::pair<unsigned int, bool>>{
                {KEY_LEFTCTRL, true}, {KEY_A, true}, {KEY_LEFTCTRL, false}},
            "Lost synthetic modifier fallback");
    key(session, 0x41, NONE, KEY_RELEASE);
    require(recorder.down.empty(), "Synthetic modifier remained stuck");

    // Held modifier state must not leak between streaming sessions.
    key(session, M_LCTRL, CTRL);
    events::StreamSession second{};
    auto second_display = virtual_display::create_wayland_display(element, "second");
    second.keyboard->emplace(std::in_place_type<virtual_display::WaylandKeyboard>, second_display);
    recorder.keys.clear();
    key(second, 0x41, CTRL);
    require(recorder.keys.size() == 3, "Physical modifier state leaked between sessions");
    key(second, 0x41, NONE, KEY_RELEASE);
    key(session, M_LCTRL, NONE, KEY_RELEASE);
    std::cout << "PASS: 10 modifier codes, held letters, left/right clicks, key-up, fallback, session isolation\n";
  } catch (const std::exception &e) {
    std::cerr << "FAIL: " << e.what() << '\n';
    return 1;
  }
}
