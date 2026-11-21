import sys
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kivy.config import Config

Config.set("input", "mouse", "mouse,disable_multitouch")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.uix.widget import Widget
from kivy.core.window import Keyboard, Window
from kivy.event import EventDispatcher

try:
    from kivymd.app import MDApp
    HAS_MD = True
except ImportError:
    HAS_MD = False

try:
    from kivy_garden.mapview import MapLayer, MapMarker, MapView
    HAS_MAPVIEW = True
except ImportError:
    MapLayer = Widget
    HAS_MAPVIEW = False

from engine_loader import EngineLoader
from crowdsource import save_report
from location_service import (
    LocationService,
    LocationServiceError,
    Place,
)


PALETTE = {
    "canvas": (0.94, 0.96, 0.98, 1),
    "surface": (1, 1, 1, 1),
    "ink": (0.09, 0.14, 0.21, 1),
    "muted": (0.36, 0.42, 0.50, 1),
    "line": (0.84, 0.88, 0.92, 1),
    "primary": (0.12, 0.34, 0.72, 1),
    "green": (0.10, 0.55, 0.36, 1),
}


class Surface(BoxLayout):
    background_color = ListProperty(PALETTE["surface"])
    border_color = ListProperty(PALETTE["line"])
    border_width = NumericProperty(dp(1))
    radius = NumericProperty(dp(14))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            self.fill_color = Color(*self.background_color)
            self.fill_shape = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius]
            )
        with self.canvas.after:
            self.outline_color = Color(*self.border_color)
            self.outline_shape = Line(
                rounded_rectangle=(*self.pos, *self.size, self.radius),
                width=self.border_width,
            )
        self.bind(
            pos=self._update_surface,
            size=self._update_surface,
            background_color=self._update_surface,
            border_color=self._update_surface,
            border_width=self._update_surface,
            radius=self._update_surface,
        )

    def _update_surface(self, *_):
        self.fill_color.rgba = self.background_color
        self.fill_shape.pos = self.pos
        self.fill_shape.size = self.size
        self.fill_shape.radius = [self.radius]
        self.outline_color.rgba = self.border_color
        self.outline_shape.rounded_rectangle = (*self.pos, *self.size, self.radius)
        self.outline_shape.width = self.border_width


class TrackActionButton(Button):
    fill = ListProperty(PALETTE["primary"])
    radius = NumericProperty(dp(12))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.bold = True
        with self.canvas.before:
            self.fill_instruction = Color(*self.fill)
            self.shape = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius]
            )
        self.bind(pos=self._update_shape, size=self._update_shape, fill=self._update_shape)

    def _update_shape(self, *_):
        self.fill_instruction.rgba = self.fill
        self.shape.pos = self.pos
        self.shape.size = self.size
        self.shape.radius = [self.radius]


def _hex_color(value, fallback):
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            return tuple(
                int(value[index:index + 2], 16) / 255.0
                for index in (1, 3, 5)
            ) + (1,)
        except ValueError:
            pass
    return tuple(fallback) + ((1,) if len(fallback) == 3 else ())


def _format_rupiah(amount):
    return "Rp {:,.0f}".format(amount).replace(",", ".")


class RouteStepRow(BoxLayout):
    MODE_LABELS = {
        "angkot": ("A", "ANGKOT"),
        "damri": ("B", "BUS"),
        "kereta": ("K", "KERETA"),
        "jalan_kaki": ("W", "JALAN"),
    }

    def __init__(self, step, fallback_color, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(6),
            **kwargs,
        )
        mode = step.get("mode", "angkot")
        color = _hex_color(step.get("color_hex"), fallback_color)
        icon_text, mode_text = self.MODE_LABELS.get(
            mode, (mode[:1].upper(), mode.upper())
        )

        marker_column = BoxLayout(
            orientation="vertical",
            size_hint_x=None,
            width=dp(62),
            spacing=dp(2),
        )
        marker = Surface(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            radius=dp(12),
            border_width=dp(0.5),
            background_color=color,
            border_color=color,
        )
        marker.add_widget(Label(
            text=icon_text,
            color=PALETTE["surface"],
            bold=True,
            font_size=dp(11),
        ))
        marker_column.add_widget(marker)
        marker_column.add_widget(Label(
            text=mode_text,
            color=color,
            bold=True,
            font_size=dp(8),
            size_hint_y=None,
            height=dp(11),
        ))
        self.add_widget(marker_column)

        route_code = step.get("route_code") or step.get("route_id", "")
        route_name = step.get("route_name", "")
        route_title = route_name
        if route_code and route_code != route_name:
            route_title = "{} · {}".format(route_code, route_name)
        from_stop = step.get("from_stop") or step.get("from", "Titik awal")
        to_stop = step.get("to_stop") or step.get("to", "Titik tujuan")
        self.detail_label = Label(
            text="{}\nNaik di {} -> Turun di {} · {} mnt".format(
                route_title,
                from_stop,
                to_stop,
                step.get("duration_minutes", 0),
            ),
            color=PALETTE["ink"],
            font_size=dp(10),
            halign="left",
            valign="top",
            size_hint=(1, None),
            height=dp(34),
            text_size=(dp(160), None),
        )
        self.detail_label.bind(
            width=self._sync_detail_text,
            texture_size=self._update_height,
        )
        self.add_widget(self.detail_label)

        fare = step.get("fare_rupiah", 0)
        self.fare_label = Label(
            text=_format_rupiah(fare) if fare else "Gratis",
            color=PALETTE["ink"],
            bold=True,
            font_size=dp(10),
            halign="right",
            valign="top",
            shorten=True,
            max_lines=1,
            size_hint_x=None,
            size_hint_y=None,
            width=dp(76),
            height=dp(18),
        )
        self.fare_label.bind(
            size=lambda widget, size: setattr(widget, "text_size", size)
        )
        self.add_widget(self.fare_label)
        self.bind(size=self._layout_row, parent=self._layout_row)
        self._layout_row()

    def _update_height(self, _widget, texture_size):
        self.detail_label.height = max(dp(34), texture_size[1])
        self.height = max(dp(44), self.detail_label.height)

    def _sync_detail_text(self, widget, width):
        widget.text_size = (max(1, width), None)
        widget.texture_update()

    def _layout_row(self, *_):
        if self.parent is not None and self.width > 0:
            self.do_layout()


class RouteOptionCard(ButtonBehavior, Surface):
    selection = NumericProperty(0)
    expand_progress = NumericProperty(0)
    COLLAPSED_HEIGHT = dp(104)

    def __init__(self, route, color, on_select, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=self.COLLAPSED_HEIGHT,
            padding=dp(10),
            spacing=dp(5),
            border_width=dp(1),
            **kwargs,
        )
        self.route = route
        self.route_color = tuple(color) + ((1,) if len(color) == 3 else ())
        self.on_select = on_select
        self._detail_height = 0
        self.bind(
            on_release=lambda *_: on_select(),
            selection=self._apply_selection,
            expand_progress=self._apply_expansion,
        )

        header = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(6))
        title = Label(
            text=route.get("display_name", "Pilihan rute"),
            color=PALETTE["ink"],
            bold=True,
            font_size=dp(12),
            halign="left",
            valign="middle",
        )
        title.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        header.add_widget(title)
        total_fare = Label(
            text=_format_rupiah(route.get("fare_rupiah", 0)),
            color=PALETTE["ink"],
            bold=True,
            font_size=dp(13),
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(88),
        )
        total_fare.bind(
            size=lambda widget, size: setattr(widget, "text_size", size)
        )
        header.add_widget(total_fare)
        self.add_widget(header)

        self.badge_scroll = ScrollView(
            size_hint=(1, None),
            height=dp(25),
            do_scroll_x=True,
            do_scroll_y=False,
            bar_width=0,
        )
        badge_row = BoxLayout(
            orientation="horizontal",
            size_hint=(None, 1),
            spacing=dp(4),
        )
        badge_row.bind(minimum_width=badge_row.setter("width"))
        badges = route.get("route_badges") or [{
            "mode_label": "ANGKOT",
            "route_id": "Trayek",
            "route_name": route.get("route_name", "Angkot"),
        }]
        for index, badge in enumerate(badges):
            if index:
                badge_row.add_widget(Label(
                    text=">",
                    color=PALETTE["muted"],
                    size_hint_x=None,
                    width=dp(10),
                    font_size=dp(10),
                ))
            mode_label = {
                "JALAN": "Jalan Kaki",
                "BUS": "Damri",
                "ANGKOT": "Angkot",
                "KERETA": "Kereta",
            }.get(badge.get("mode_label", ""), badge.get("mode_label", "Rute"))
            route_code = badge.get("route_code") or badge.get("route_id", "")
            text = mode_label if mode_label == "Jalan Kaki" else (
                "{} {}".format(mode_label, route_code) if route_code else mode_label
            )
            badge_color = _hex_color(
                badge.get("color_hex"), self.route_color
            )
            pill = Surface(
                orientation="horizontal",
                size_hint=(None, None),
                height=dp(23),
                padding=[dp(7), dp(1)],
                radius=dp(11),
                border_width=dp(0.7),
                background_color=(
                    badge_color[0], badge_color[1], badge_color[2], 0.10
                ),
                border_color=(
                    badge_color[0], badge_color[1], badge_color[2], 0.5
                ),
            )
            pill.bind(minimum_width=pill.setter("width"))
            badge_label = Label(
                text=text,
                color=badge_color,
                bold=True,
                font_size=dp(9),
                size_hint=(None, 1),
            )
            badge_label.bind(
                texture_size=lambda widget, size: setattr(widget, "width", size[0])
            )
            pill.add_widget(badge_label)
            badge_row.add_widget(pill)
        self.badge_scroll.add_widget(badge_row)
        self.add_widget(self.badge_scroll)

        summary = BoxLayout(size_hint_y=None, height=dp(19), spacing=dp(6))
        summary.add_widget(Label(
            text="{} mnt".format(route.get("duration_minutes", 0)),
            color=PALETTE["muted"],
            font_size=dp(10),
            halign="left",
            valign="middle",
        ))
        times = Label(
            text="{} - {}".format(
                route.get("departure", "--:--"),
                route.get("arrival", "--:--"),
            ),
            color=PALETTE["muted"],
            font_size=dp(10),
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(112),
        )
        times.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        summary.add_widget(times)
        self.add_widget(summary)

        self.details = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=0,
            spacing=dp(6),
            opacity=0,
        )
        self.details.bind(minimum_height=self._set_detail_height)
        for step in route.get("steps", []):
            self.details.add_widget(RouteStepRow(step, self.route_color))
        self.add_widget(self.details)
        self._apply_selection()
        self._apply_expansion()

    def set_selected(self, selected):
        Animation.cancel_all(self, "selection")
        Animation.cancel_all(self, "expand_progress")
        Animation(
            selection=1 if selected else 0,
            duration=0.22,
            t="out_cubic",
        ).start(self)
        Animation(
            expand_progress=1 if selected else 0,
            duration=0.28,
            t="out_cubic",
        ).start(self)

    def _set_detail_height(self, _details, height):
        self._detail_height = height
        self._apply_expansion()

    def _apply_expansion(self, *_):
        progress = self.expand_progress
        self.details.height = self._detail_height * progress
        self.details.opacity = progress
        self.height = self.COLLAPSED_HEIGHT + self._detail_height * progress

    def _apply_selection(self, *_):
        amount = self.selection
        self.border_color = tuple(
            PALETTE["line"][i] * (1 - amount) + self.route_color[i] * amount
            for i in range(4)
        )
        self.border_width = dp(1) + dp(1.5) * amount
        self.background_color = (
            1 - (1 - self.route_color[0]) * amount * 0.06,
            1 - (1 - self.route_color[1]) * amount * 0.06,
            1 - (1 - self.route_color[2]) * amount * 0.06,
            1,
        )


class RoutePolylineLayer(MapLayer):
    def __init__(self, coordinates, color, segments=None, **kwargs):
        super().__init__(**kwargs)
        self.coordinates = coordinates
        self.route_color = color
        self.segments = segments or []

    def reposition(self):
        map_view = self.parent
        if map_view is None:
            return
        self.canvas.clear()
        with self.canvas:
            segments = self.segments or [{
                "coordinates": self.coordinates,
                "mode": "angkot",
                "color": self.route_color,
            }]
            for segment in segments:
                coordinates = segment["coordinates"]
                if len(coordinates) < 2:
                    continue
                points = []
                for point in coordinates:
                    x, y = map_view.get_window_xy_from(
                        point["lat"], point["lon"], map_view.zoom
                    )
                    points.extend((x, y))
                Color(0.06, 0.10, 0.16, 0.92)
                Line(points=points, width=dp(6), joint="round", cap="round")
                Color(*segment["color"])
                if segment["mode"] == "kereta":
                    Line(
                        points=points,
                        width=dp(4),
                        dash_length=dp(10),
                        dash_offset=dp(5),
                    )
                else:
                    Line(points=points, width=dp(4), joint="round", cap="round")


class CenterCrosshair(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(0.82, 0.16, 0.18, 1)
            self.circle = Line(circle=(0, 0, dp(10)), width=dp(2))
            self.horizontal = Line(points=[], width=dp(2))
            self.vertical = Line(points=[], width=dp(2))
            Color(1, 1, 1, 1)
            self.center_dot = Line(circle=(0, 0, dp(2.5)), width=dp(2))
        self.bind(pos=self._update, size=self._update)

    def _update(self, *_):
        center_x = self.center_x
        center_y = self.center_y
        self.circle.circle = (center_x, center_y, dp(10))
        self.horizontal.points = [
            center_x - dp(17), center_y, center_x + dp(17), center_y
        ]
        self.vertical.points = [
            center_x, center_y - dp(17), center_x, center_y + dp(17)
        ]
        self.center_dot.circle = (center_x, center_y, dp(2.5))


class CameraTween(EventDispatcher):
    progress = NumericProperty(0)


def paint_background(widget, color):
    with widget.canvas.before:
        Color(*color)
        rectangle = Rectangle(pos=widget.pos, size=widget.size)

    def update_rectangle(instance, *_):
        rectangle.pos = instance.pos
        rectangle.size = instance.size

    widget.bind(pos=update_rectangle, size=update_rectangle)


class FallbackMap(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.points = []
        self.markers = []
        self.canvas_color = (0.12, 0.16, 0.22)
        self.bind(size=self.redraw, pos=self.redraw)

    def set_route(self, polyline, color):
        self.points = polyline
        self.route_color = color
        self.redraw()

    def set_locations(self, locations):
        self.markers = locations
        self.redraw()

    def redraw(self, *args):
        self.canvas.before.clear()
        self.canvas.clear()
        with self.canvas.before:
            Color(*self.canvas_color)
            Rectangle(pos=self.pos, size=self.size)
        if not self.points:
            return

        all_lats = [p["lat"] for p in self.points]
        all_lons = [p["lon"] for p in self.points]
        if len(all_lats) == 1:
            all_lats.append(all_lats[0] + 0.001)
            all_lons.append(all_lons[0] + 0.001)
        lat_min, lat_max = min(all_lats), max(all_lats)
        lon_min, lon_max = min(all_lons), max(all_lons)
        lat_span = max(lat_max - lat_min, 0.001)
        lon_span = max(lon_max - lon_min, 0.001)

        def xy(point):
            x = self.x + 30 + (point["lon"] - lon_min) / lon_span * (self.width - 60)
            y = self.y + 30 + (point["lat"] - lat_min) / lat_span * (self.height - 60)
            return x, y

        window_points = [coordinate for point in self.points for coordinate in xy(point)]
        with self.canvas:
            Color(0.06, 0.10, 0.16, 0.92)
            if len(window_points) >= 4:
                Line(points=window_points, width=dp(6), joint="round", cap="round")
            Color(*getattr(self, "route_color", (0.2, 0.6, 1.0)))
            if len(window_points) >= 4:
                Line(points=window_points, width=dp(4), joint="round", cap="round")
            for point in self.points:
                x, y = xy(point)
                Color(1, 1, 1, 1)
                Line(circle=(x, y, dp(5)), width=dp(2))


class RouteMap(StencilView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.markers = []
        self.route_layer = None
        self.pin_overlay = None
        self.pin_center_callback = None
        self.fallback_center = (-6.9175, 107.6191)
        self._pressed_ctrl_keys = set()
        self._ctrl_zoom_touch = None
        self._ctrl_zoom_last_y = None
        if HAS_MAPVIEW:
            self.map = MapView(
                lat=-6.9175, lon=107.6191, zoom=12,
                double_tap_zoom=True,
                size_hint=(None, None),
                pos=self.pos,
                size=self.size,
            )
            self.map._scatter.do_scale = False
            Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
            Window.bind(on_focus=self._on_window_focus)
            self.add_widget(self.map)
        else:
            self.map = FallbackMap(
                size_hint=(None, None), pos=self.pos, size=self.size
            )
            self.add_widget(self.map)
        self.bind(pos=self._sync_map_geometry, size=self._sync_map_geometry)
        self._sync_map_geometry()

    def _sync_map_geometry(self, *_):
        self.map.pos = self.pos
        self.map.size = self.size

    def _set_ctrl_scale(self, enabled):
        if HAS_MAPVIEW:
            self.map._scatter.do_scale = enabled

    def _on_key_down(self, _window, key, *_):
        if key in (Keyboard.keycodes["lctrl"], Keyboard.keycodes["rctrl"]):
            self._pressed_ctrl_keys.add(key)
            self._set_ctrl_scale(True)

    def _on_key_up(self, _window, key, *_):
        if key in self._pressed_ctrl_keys:
            self._pressed_ctrl_keys.discard(key)
            self._set_ctrl_scale(bool(self._pressed_ctrl_keys))

    def _on_window_focus(self, _window, focused):
        if not focused and self._pressed_ctrl_keys:
            self._pressed_ctrl_keys.clear()
            self._set_ctrl_scale(False)

    def unbind_keyboard(self):
        if HAS_MAPVIEW:
            Window.unbind(
                on_key_down=self._on_key_down,
                on_key_up=self._on_key_up,
                on_focus=self._on_window_focus,
            )
            self._pressed_ctrl_keys.clear()
            self._set_ctrl_scale(False)

    def on_touch_down(self, touch):
        if (
            HAS_MAPVIEW
            and self._pressed_ctrl_keys
            and "button" in touch.profile
            and touch.button == "left"
            and self.collide_point(*touch.pos)
        ):
            self._ctrl_zoom_touch = touch.uid
            self._ctrl_zoom_last_y = touch.y
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and touch.uid == self._ctrl_zoom_touch:
            if self._pressed_ctrl_keys:
                delta_y = touch.y - self._ctrl_zoom_last_y
                self._ctrl_zoom_last_y = touch.y
                if delta_y:
                    self.map.animated_diff_scale_at(
                        delta_y / dp(120), *touch.pos
                    )
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self and touch.uid == self._ctrl_zoom_touch:
            touch.ungrab(self)
            self._ctrl_zoom_touch = None
            self._ctrl_zoom_last_y = None
            return True
        return super().on_touch_up(touch)

    def clear_markers(self):
        if not HAS_MAPVIEW:
            self.map.set_locations([])
            return
        for marker in self.markers:
            self.map.remove_marker(marker)
        self.markers.clear()

    def show_locations(self, start, goal):
        if not HAS_MAPVIEW:
            self.map.set_locations([start, goal])
            return
        self.clear_markers()
        for stop in (start, goal):
            marker = MapMarker(lat=stop["lat"], lon=stop["lon"])
            self.markers.append(marker)
            self.map.add_marker(marker)

    def show_route(self, polyline, color, segments=None):
        if not HAS_MAPVIEW:
            self.map.set_route(polyline, color)
            return
        if not polyline:
            return
        if self.route_layer is not None:
            self.map.remove_layer(self.route_layer)
        self.route_layer = RoutePolylineLayer(polyline, color, segments)
        self.map.add_layer(self.route_layer, mode="window")
        self.route_layer.reposition()
        self.focus_route(polyline)

    def clear_route(self):
        if self.route_layer is not None and HAS_MAPVIEW:
            self.map.remove_layer(self.route_layer)
            self.route_layer = None
        elif not HAS_MAPVIEW:
            self.map.set_route([], (0.2, 0.6, 1.0))

    def center_coordinates(self):
        if HAS_MAPVIEW:
            return self.map.lat, self.map.lon
        return self.fallback_center

    def center_on(self, lat, lon):
        self.fallback_center = (lat, lon)
        if HAS_MAPVIEW:
            self.map.center_on(lat, lon)

    def begin_pin_drop(self, on_confirm, on_cancel, on_center_change):
        self.cancel_pin_drop()
        self.pin_center_callback = on_center_change
        self.pin_overlay = FloatLayout()
        crosshair = CenterCrosshair(
            size_hint=(None, None),
            size=(dp(42), dp(42)),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )
        self.pin_overlay.add_widget(crosshair)

        card = Surface(
            orientation="vertical",
            size_hint=(0.84, None),
            height=dp(126),
            padding=dp(12),
            spacing=dp(5),
            pos_hint={"center_x": 0.5, "y": 0.035},
            background_color=PALETTE["surface"],
            border_color=PALETTE["line"],
        )
        self.pin_name_label = Label(
            text="Mengambil nama jalan...",
            color=PALETTE["ink"],
            bold=True,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(25),
        )
        self.pin_name_label.bind(
            size=lambda widget, size: setattr(widget, "text_size", size)
        )
        self.pin_coordinates_label = Label(
            text="",
            color=PALETTE["muted"],
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        )
        self.pin_coordinates_label.bind(
            size=lambda widget, size: setattr(widget, "text_size", size)
        )
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        cancel = TrackActionButton(
            text="Batal",
            fill=(0.89, 0.92, 0.96, 1),
            color=PALETTE["primary"],
        )
        confirm = TrackActionButton(text="Tetapkan Lokasi Ini")
        cancel.bind(on_release=lambda *_: on_cancel())
        confirm.bind(on_release=lambda *_: on_confirm())
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        card.add_widget(self.pin_name_label)
        card.add_widget(self.pin_coordinates_label)
        card.add_widget(actions)
        self.pin_overlay.add_widget(card)
        self.add_widget(self.pin_overlay)
        if HAS_MAPVIEW:
            self.map.bind(lat=self._notify_map_center, lon=self._notify_map_center)
        self._notify_map_center()

    def cancel_pin_drop(self):
        if self.pin_overlay is not None:
            self.remove_widget(self.pin_overlay)
            self.pin_overlay = None
        if HAS_MAPVIEW and self.pin_center_callback is not None:
            self.map.unbind(lat=self._notify_map_center, lon=self._notify_map_center)
        self.pin_center_callback = None

    def show_pin_status(self, name, lat, lon):
        if self.pin_overlay is None:
            return
        self.pin_name_label.text = name
        self.pin_coordinates_label.text = "{:.6f}, {:.6f}".format(lat, lon)

    def _notify_map_center(self, *_):
        if self.pin_center_callback is not None:
            lat, lon = self.center_coordinates()
            self.pin_center_callback(lat, lon)

    def focus_route(self, polyline):
        lats = [point["lat"] for point in polyline]
        lons = [point["lon"] for point in polyline]
        south, north = min(lats), max(lats)
        west, east = min(lons), max(lons)
        center_lat = (south + north) / 2
        center_lon = (west + east) / 2

        if not HAS_MAPVIEW:
            return
        source = self.map.map_source
        min_zoom = source.get_min_zoom()
        max_zoom = min(source.get_max_zoom(), 17)
        zoom = min_zoom
        for candidate in range(max_zoom, min_zoom - 1, -1):
            route_width = abs(
                source.get_x(candidate, east) - source.get_x(candidate, west)
            ) * self.map.scale
            route_height = abs(
                source.get_y(candidate, north) - source.get_y(candidate, south)
            ) * self.map.scale
            if route_width <= self.map.width * 0.76 and route_height <= self.map.height * 0.76:
                zoom = candidate
                break

        if not hasattr(self, "camera_tween"):
            self.camera_tween = CameraTween()
        Animation.cancel_all(self.camera_tween, "progress")
        Animation.cancel_all(self.map._scatter, "scale")
        self.camera_tween.progress = 0
        start_lat, start_lon = self.map.lat, self.map.lon
        pan = Animation(progress=1, duration=0.48, t="out_cubic")
        pan.bind(on_progress=lambda _animation, _widget, value: self.map.center_on(
            start_lat + (center_lat - start_lat) * value,
            start_lon + (center_lon - start_lon) * value,
        ))
        pan.start(self.camera_tween)
        Clock.unschedule(self.map._animate_scale)
        self.map._scale_target_anim = False
        self.map._scale_target = 0
        self.map.animated_diff_scale_at(zoom - int(self.map.zoom), *self.map.center)


class TrackSumApp(MDApp if HAS_MD else App):
    ROUTE_COLORS = [
        (0.88, 0.20, 0.20),
        (1.00, 0.62, 0.05),
        (0.18, 0.60, 0.32),
        (0.20, 0.45, 0.85),
    ]
    ROUTE_TITLES = [
        "Tercepat / Mahal",
        "Cepat & Seimbang",
        "Hemat & Santai",
        "Termurah / Lambat",
    ]

    def build(self):
        Window.clearcolor = (0.95, 0.96, 0.98, 1)
        self.title = "TrackSum - Bandung"
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tracksum")
        self._engine_lock = threading.Lock()
        self._route_generation = 0
        self._place_search_generation = 0
        self._pin_generation = 0
        self._pin_reverse_event = None

        try:
            self.engine = EngineLoader()
            self.stops = self.engine.list_stops()
        except Exception as exc:
            self.engine_error = str(exc)
            self.engine = None
            self.stops = []
        self.route_data = json.loads(
            (ROOT / "data" / "bandung_routes.json").read_text(encoding="utf-8")
        )
        self.location_service = LocationService()

        root = BoxLayout(orientation="horizontal", padding=dp(14), spacing=dp(14))
        self.root_layout = root
        paint_background(root, PALETTE["canvas"])
        sidebar = Surface(
            orientation="vertical",
            size_hint=(0.37, 1),
            padding=[dp(14), dp(8), dp(14), dp(10)],
            spacing=dp(7),
            radius=dp(20),
            background_color=PALETTE["surface"],
            border_color=(0.88, 0.90, 0.93, 1),
            border_width=dp(0.8),
        )
        self.sidebar = sidebar
        sidebar.add_widget(Label(
            text="TrackSum",
            color=PALETTE["ink"],
            bold=True,
            font_size=dp(24),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(38),
        ))
        sidebar.add_widget(Label(
            text="Angkot, bus, dan kereta Bandung Raya.",
            color=PALETTE["muted"],
            font_size=dp(12),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(20),
        ))

        locations = Surface(
            orientation="vertical",
            size_hint_y=None,
            height=dp(126),
            padding=[dp(8), dp(6)],
            spacing=dp(4),
            radius=dp(14),
            background_color=(0.97, 0.98, 1, 1),
            border_color=PALETTE["line"],
        )
        self.start_place = self._place_for_stop("alun_alun")
        self.goal_place = self._place_for_stop("ledeng")
        self.start_button = self._location_button("A")
        self.goal_button = self._location_button("B")
        self._update_location_buttons()
        locations.add_widget(self._location_row(self.start_button, "A", (0.12, 0.55, 0.36, 1)))
        locations.add_widget(self._location_row(self.goal_button, "B", (0.83, 0.25, 0.24, 1)))
        sidebar.add_widget(locations)

        swap_row = BoxLayout(size_hint_y=None, height=dp(30))
        swap_row.add_widget(Widget())
        swap = Button(
            text="↕  Tukar arah",
            size_hint=(None, 1),
            width=dp(124),
            color=PALETTE["primary"],
            background_normal="",
            background_color=(0, 0, 0, 0),
        )
        swap.bind(on_release=lambda *_: self.swap_locations())
        swap_row.add_widget(swap)
        sidebar.add_widget(swap_row)

        departure_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        departure_row.add_widget(Label(
            text="Berangkat",
            color=PALETTE["muted"],
            size_hint_x=None,
            width=dp(86),
            halign="left",
        ))
        self.time_field = TextInput(
            text="07:30",
            multiline=False,
            size_hint_y=None,
            height=dp(40),
            font_size=dp(15),
            foreground_color=PALETTE["ink"],
            cursor_color=PALETTE["primary"],
            background_normal="",
            background_active="",
            background_color=(0.96, 0.97, 0.99, 1),
            padding=[dp(12), dp(10)],
        )
        departure_row.add_widget(self.time_field)
        sidebar.add_widget(departure_row)
        self.time_field.bind(text=lambda *_: self._schedule_auto_route())
        self.route_status = Label(
            text="Pencarian rute otomatis aktif.",
            color=PALETTE["muted"],
            font_size=dp(11),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        )
        self.route_status.bind(
            width=lambda widget, width: setattr(
                widget, "text_size", (width, None)
            ),
            texture_size=lambda widget, size: setattr(
                widget, "height", max(dp(22), size[1])
            ),
        )
        sidebar.add_widget(self.route_status)
        sidebar.add_widget(Label(
            text="PILIHAN RUTE",
            color=PALETTE["muted"],
            bold=True,
            font_size=dp(11),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        ))

        self.route_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.route_list.bind(minimum_height=self.route_list.setter("height"))
        scroll = ScrollView(size_hint=(1, 1), bar_width=dp(5), do_scroll_x=False)
        scroll.add_widget(self.route_list)
        sidebar.add_widget(scroll)

        report_button = TrackActionButton(
            text="!  Lapor Tarif / Macet",
            size_hint_y=None,
            height=dp(44),
            fill=(0.91, 0.94, 0.98, 1),
            radius=dp(12),
        )
        report_button.color = PALETTE["primary"]
        report_button.bind(on_release=lambda *_: self.open_report_dialog())
        sidebar.add_widget(report_button)

        self.map_panel = RouteMap(size_hint=(0.63, 1))
        root.add_widget(sidebar)
        root.add_widget(self.map_panel)
        self._route_trigger = Clock.create_trigger(self._start_route_search, 0.25)
        Clock.schedule_once(lambda *_: self.populate_initial_state(), 0.1)
        return root

    def on_stop(self):
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False, cancel_futures=True)
        if hasattr(self, "map_panel"):
            self.map_panel.unbind_keyboard()

    def _stop_by_id(self, stop_id):
        return next((stop for stop in self.stops if stop["id"] == stop_id), None)

    def _place_for_stop(self, stop_id):
        stop = self._stop_by_id(stop_id)
        if stop is None:
            raise LocationServiceError("Halte lokal tidak ditemukan: " + stop_id)
        return Place(
            id=stop["id"],
            name=stop["name"],
            lat=stop["lat"],
            lon=stop["lon"],
            source="local",
        )

    @staticmethod
    def get_text(field):
        return field.text.strip()

    def _location_button(self, pin):
        button = Button(
            text="Pilih lokasi",
            halign="left",
            valign="middle",
            color=PALETTE["ink"],
            font_size=dp(14),
            background_normal="",
            background_color=(0, 0, 0, 0),
        )
        button.bind(size=lambda widget, size: setattr(widget, "text_size", (size[0], None)))
        button.bind(on_release=lambda *_: self.open_location_menu(pin))
        return button

    def _update_location_buttons(self):
        if hasattr(self, "start_button"):
            self.start_button.text = self.start_place.name
        if hasattr(self, "goal_button"):
            self.goal_button.text = self.goal_place.name

    def _location_row(self, button, pin, color):
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        pin_label = Label(
            text=pin,
            color=color,
            bold=True,
            font_size=dp(16),
            size_hint_x=None,
            width=dp(28),
        )
        row.add_widget(pin_label)
        row.add_widget(button)
        return row

    def open_location_menu(self, pin):
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        popup = Popup(
            title="Pilih titik " + ("awal" if pin == "A" else "tujuan"),
            content=content,
            size_hint=(0.05, 0.05),
            opacity=0,
        )

        def choose(action):
            popup.dismiss()
            Clock.schedule_once(lambda _dt: action(), 0.12)

        actions = (
            ("◎  Gunakan Lokasi Saya", lambda: self.request_current_location(pin)),
            ("⌕  Cari Nama Tempat / POI", lambda: self.open_place_search(pin)),
            ("⌖  Pilih Titik di Peta", lambda: self.enter_pin_drop(pin)),
        )
        for title, action in actions:
            button = TrackActionButton(
                text=title,
                size_hint_y=None,
                height=dp(48),
                fill=PALETTE["primary"],
            )
            button.bind(on_release=lambda *_args, callback=action: choose(callback))
            content.add_widget(button)
        popup.open()
        Animation(
            size_hint=(0.62, 0.34),
            opacity=1,
            duration=0.2,
            t="out_quad",
        ).start(popup)

    def _set_location(self, pin, place):
        if pin == "A":
            self.start_place = place
        else:
            self.goal_place = place
        self._update_location_buttons()
        self._schedule_auto_route()

    def request_current_location(self, pin):
        if self.location_service is None:
            self.show_popup(
                "Layanan lokasi tidak siap",
                getattr(self, "location_error", "LocationService tidak tersedia."),
            )
            return
        self.route_status.text = "Mengambil lokasi perangkat..."
        future = self.executor.submit(self.location_service.get_current_location)

        def complete(done):
            def update(_dt):
                try:
                    place = done.result()
                except Exception as exc:
                    self.route_status.text = "Lokasi gagal diperoleh."
                    self.show_popup("Lokasi tidak tersedia", str(exc))
                    return
                self._set_location(pin, place)

            Clock.schedule_once(update, 0)

        future.add_done_callback(complete)

    def open_place_search(self, pin):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        search = TextInput(
            hint_text="Nama tempat, halte, atau stasiun",
            multiline=False,
            size_hint_y=None,
            height=dp(44),
            foreground_color=PALETTE["ink"],
            background_normal="",
            background_active="",
            background_color=(0.96, 0.97, 0.99, 1),
            padding=[dp(12), dp(10)],
        )
        status = Label(
            text="Hasil halte lokal ditampilkan lebih dahulu.",
            color=PALETTE["muted"],
            size_hint_y=None,
            height=dp(28),
            halign="left",
        )
        options = GridLayout(cols=1, spacing=dp(5), size_hint_y=None)
        options.bind(minimum_height=options.setter("height"))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(options)
        content.add_widget(search)
        content.add_widget(status)
        content.add_widget(scroll)
        popup = Popup(
            title="Cari lokasi " + ("awal" if pin == "A" else "tujuan"),
            content=content,
            size_hint=(0.05, 0.05),
            opacity=0,
        )
        search_state = {"generation": 0, "event": None}

        def populate(places, remote_error=None):
            options.clear_widgets()
            if remote_error:
                status.text = "Pencarian online gagal: {}".format(
                    remote_error[:100]
                )
            elif places:
                status.text = "Pilih hasil lokasi."
            else:
                status.text = "Tidak ada hasil. Coba nama tempat lain."
            for place in places:
                item = Button(
                    text="{}  ·  {}".format(
                        place.name,
                        "Lokal" if place.source == "local" else "OpenStreetMap",
                    ),
                    color=PALETTE["ink"],
                    halign="left",
                    size_hint_y=None,
                    height=dp(48),
                    background_normal="",
                    background_color=(0.97, 0.98, 1, 1),
                )
                item.bind(
                    on_release=lambda _button, selected=place: choose(selected)
                )
                options.add_widget(item)

        def finish_search(done, generation):
            def update(_dt):
                if generation != search_state["generation"] or not popup.is_open:
                    return
                try:
                    result = done.result()
                except Exception as exc:
                    status.text = "Pencarian online gagal: {}".format(exc)
                    return
                populate(result.places, result.remote_error)

            Clock.schedule_once(update, 0)

        def search_remote(query, generation):
            if not query:
                return
            future = self.executor.submit(
                self.location_service.search_places, query, 8
            )
            future.add_done_callback(
                lambda done: finish_search(done, generation)
            )

        def on_query(_field, query):
            search_state["generation"] += 1
            generation = search_state["generation"]
            if search_state["event"] is not None:
                search_state["event"].cancel()
            local = (
                self.location_service.search_local(query, 8)
                if query.strip() else self.location_service.local_stops[:8]
            )
            populate(local)
            search_state["event"] = Clock.schedule_once(
                lambda _dt: search_remote(query.strip(), generation), 0.65
            )

        def choose(place):
            if search_state["event"] is not None:
                search_state["event"].cancel()
            popup.dismiss()
            self._set_location(pin, place)

        search.bind(text=on_query)
        populate(self.location_service.local_stops[:8])
        popup.open()
        Animation(
            size_hint=(0.66, 0.72),
            opacity=1,
            duration=0.2,
            t="out_quad",
        ).start(popup)

    def enter_pin_drop(self, pin):
        self.pin_mode = pin
        self._pin_place_name = None
        self._pin_geocoded_coordinates = None
        self.root_layout.padding = 0
        self.root_layout.spacing = 0
        self.sidebar.disabled = True
        self.map_panel.begin_pin_drop(
            self.confirm_pin_drop,
            self.cancel_pin_drop,
            self._on_pin_center_change,
        )
        Animation(
            size_hint_x=0,
            opacity=0,
            duration=0.28,
            t="out_cubic",
        ).start(self.sidebar)
        Animation(size_hint_x=1, duration=0.28, t="out_cubic").start(
            self.map_panel
        )

    def cancel_pin_drop(self):
        self._pin_generation += 1
        if self._pin_reverse_event is not None:
            self._pin_reverse_event.cancel()
            self._pin_reverse_event = None
        self.map_panel.cancel_pin_drop()
        self.pin_mode = None
        self._restore_sidebar()

    def _restore_sidebar(self):
        self.sidebar.disabled = False
        self.root_layout.padding = dp(14)
        self.root_layout.spacing = dp(14)
        Animation(
            size_hint_x=0.37,
            opacity=1,
            duration=0.28,
            t="out_cubic",
        ).start(self.sidebar)
        Animation(size_hint_x=0.63, duration=0.28, t="out_cubic").start(
            self.map_panel
        )

    def _on_pin_center_change(self, lat, lon):
        self._pin_generation += 1
        generation = self._pin_generation
        self._pin_place_name = None
        self._pin_geocoded_coordinates = None
        self.map_panel.show_pin_status("Mencari nama jalan...", lat, lon)
        if self._pin_reverse_event is not None:
            self._pin_reverse_event.cancel()
        self._pin_reverse_event = Clock.schedule_once(
            lambda _dt: self._submit_pin_reverse(lat, lon, generation), 1.0
        )

    def _submit_pin_reverse(self, lat, lon, generation):
        future = self.executor.submit(
            self.location_service.reverse_geocode, lat, lon
        )

        def complete(done):
            def update(_dt):
                if generation != self._pin_generation or self.pin_mode is None:
                    return
                try:
                    place = done.result()
                except Exception as exc:
                    self._pin_place_name = None
                    self.map_panel.show_pin_status(
                        "Nama tempat tidak tersedia: {}".format(exc), lat, lon
                    )
                    return
                self._pin_place_name = place.name
                self._pin_geocoded_coordinates = (lat, lon)
                self.map_panel.show_pin_status(place.name, lat, lon)

            Clock.schedule_once(update, 0)

        future.add_done_callback(complete)

    def confirm_pin_drop(self):
        pin = self.pin_mode
        lat, lon = self.map_panel.center_coordinates()
        is_current_name = (
            self._pin_geocoded_coordinates is not None
            and abs(self._pin_geocoded_coordinates[0] - lat) < 1e-5
            and abs(self._pin_geocoded_coordinates[1] - lon) < 1e-5
        )
        name = self._pin_place_name if is_current_name else None
        place = Place(
            id="pin-{}-{:.6f}-{:.6f}".format(pin, lat, lon),
            name=name or "Titik peta ({:.5f}, {:.5f})".format(lat, lon),
            lat=lat,
            lon=lon,
            source="pin_drop",
        )
        self.cancel_pin_drop()
        self._set_location(pin, place)

    def swap_locations(self):
        self.start_place, self.goal_place = self.goal_place, self.start_place
        self._update_location_buttons()
        self._schedule_auto_route()

    def populate_initial_state(self):
        if self.engine is None:
            self.show_popup(
                "Engine belum siap",
                getattr(self, "engine_error", "Library native tidak ditemukan."),
            )
            return
        self._schedule_auto_route()

    @staticmethod
    def parse_waypoints(edge, reverse=False):
        points = [
            {"lat": coordinate[1], "lon": coordinate[0]}
            for coordinate in edge.get("waypoints", [])
        ]
        if reverse:
            points.reverse()
        return points

    @staticmethod
    def decode_polyline6(encoded):
        def decode_value(index):
            result = 0
            shift = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            return delta, index

        coordinates = []
        latitude = longitude = index = 0
        while index < len(encoded):
            delta, index = decode_value(index)
            latitude += delta
            delta, index = decode_value(index)
            longitude += delta
            coordinates.append({
                "lat": latitude / 1_000_000,
                "lon": longitude / 1_000_000,
            })
        return coordinates

    def _find_edge(self, route_id, start_id, goal_id):
        routes = self.route_data["routes"]
        edge = next((
            candidate for candidate in routes
            if candidate["route_id"] == route_id
            and candidate["from"] == start_id
            and candidate["to"] == goal_id
        ), None)
        if edge is not None:
            return edge, False
        edge = next((
            candidate for candidate in routes
            if candidate["route_id"] == route_id
            and candidate["from"] == goal_id
            and candidate["to"] == start_id
        ), None)
        return edge, edge is not None

    def _route_edge_path(self, route_id, start_id, goal_id):
        if start_id == goal_id:
            stop = next(
                (stop for stop in self.stops if stop["id"] == start_id),
                None,
            )
            return [] if stop is None else [{
                "lat": stop["lat"], "lon": stop["lon"]
            }]

        adjacency = {}
        for edge in self.route_data["routes"]:
            if edge.get("route_id") != route_id:
                continue
            adjacency.setdefault(edge["from"], []).append(
                (edge["to"], edge, False)
            )
            if self.route_data.get("bidirectional") or edge.get(
                "reverse_departure_minutes"
            ):
                adjacency.setdefault(edge["to"], []).append(
                    (edge["from"], edge, True)
                )

        queue = [start_id]
        parent = {start_id: None}
        cursor = 0
        while cursor < len(queue) and goal_id not in parent:
            current = queue[cursor]
            cursor += 1
            for next_stop, edge, reverse in adjacency.get(current, []):
                if next_stop in parent:
                    continue
                parent[next_stop] = (current, edge, reverse)
                queue.append(next_stop)

        if goal_id not in parent:
            return []
        edge_path = []
        current = goal_id
        while current != start_id:
            previous, edge, reverse = parent[current]
            edge_path.append((edge, reverse))
            current = previous
        edge_path.reverse()

        coordinates = []
        for edge, reverse in edge_path:
            points = self._edge_coordinates(edge, reverse)
            if coordinates and points and coordinates[-1] == points[0]:
                points = points[1:]
            coordinates.extend(points)
        return coordinates

    def _reference_geometry(self, reference, visited):
        detailed = self.route_data.get("detailed_geometries", {})
        if reference in detailed:
            start_id, goal_id = reference.split(">", 1)
            return self.decode_polyline6(detailed[reference]), start_id, goal_id
        route_id, separator, endpoints = reference.partition(":")
        if not separator or ">" not in endpoints:
            return [], "", ""
        start_id, goal_id = endpoints.split(">", 1)
        edge, reverse = self._find_edge(route_id, start_id, goal_id)
        if edge is None:
            return [], "", ""
        return self._edge_coordinates(edge, reverse, visited), start_id, goal_id

    def _edge_coordinates(self, edge, reverse=False, visited=None):
        if edge is None:
            return []
        visited = set() if visited is None else visited
        identity = (edge["route_id"], edge["from"], edge["to"], reverse)
        if identity in visited:
            return []
        visited.add(identity)

        edge_start = edge["to"] if reverse else edge["from"]
        edge_goal = edge["from"] if reverse else edge["to"]
        stops = {stop["id"]: stop for stop in self.stops}
        start = stops.get(edge_start)
        goal = stops.get(edge_goal)
        if start is None or goal is None:
            return []

        reference = edge.get("geometry_ref")
        if reference:
            points, ref_start, ref_goal = self._reference_geometry(
                reference, visited
            )
            if ref_start == edge_start and ref_goal == edge_goal:
                return points
            if ref_start == edge_goal and ref_goal == edge_start:
                return list(reversed(points))

        stored_key = "{}>{}".format(edge["from"], edge["to"])
        encoded = self.route_data.get("detailed_geometries", {}).get(stored_key)
        if encoded:
            waypoints = self.decode_polyline6(encoded)
        else:
            waypoints = self.parse_waypoints(edge)
        if reverse:
            waypoints.reverse()
        points = [{"lat": start["lat"], "lon": start["lon"]}]
        points.extend(waypoints)
        points.append({"lat": goal["lat"], "lon": goal["lon"]})
        return points

    def _route_color(self, route_id, mode, color_hex=None):
        metadata = next((
            entry for entry in self.route_data.get("route_catalog", [])
            if entry.get("route_id") == route_id
        ), {})
        value = color_hex or metadata.get("route_color")
        fallback = {
            "damri": (0.02, 0.39, 0.69),
            "kereta": (0.84, 0.11, 0.14),
            "jalan_kaki": (0.40, 0.44, 0.49),
        }.get(mode, PALETTE["green"][:3])
        return _hex_color(value, fallback)[:3]

    def route_segments(self, route):
        stops_by_name = {stop["name"]: stop for stop in self.stops}
        segments = []
        for step in route.get("steps", []):
            coordinates = step.get("coordinates")
            if coordinates is None:
                start = stops_by_name.get(step.get("from"))
                goal = stops_by_name.get(step.get("to"))
                if start is None or goal is None:
                    continue
                coordinates = self._route_edge_path(
                    step.get("route_id", ""),
                    start["id"],
                    goal["id"],
                )
                if not coordinates:
                    coordinates = [
                        {"lat": start["lat"], "lon": start["lon"]},
                        {"lat": goal["lat"], "lon": goal["lon"]},
                    ]
            segments.append({
                "mode": step.get("mode", "angkot"),
                "color": self._route_color(
                    step.get("route_id", ""),
                    step.get("mode", "angkot"),
                    step.get("color_hex"),
                ),
                "coordinates": coordinates,
            })
        return segments

    def route_geometry(self, route):
        geometry = []
        segments = self.route_segments(route)
        route["map_segments"] = segments
        for segment in segments:
            for point in segment["coordinates"]:
                if not geometry or (
                    abs(geometry[-1]["lat"] - point["lat"]) > 1e-7
                    or abs(geometry[-1]["lon"] - point["lon"]) > 1e-7
                ):
                    geometry.append(point)
        return geometry

    def _route_badges(self, route):
        known = {
            entry["route_id"]: entry
            for entry in self.route_data.get("route_catalog", [])
        }
        badges = []
        seen = set()
        for step in route.get("steps", []):
            route_id = step.get("route_id", "")
            mode = step.get("mode", "angkot")
            key = (route_id, mode)
            if route_id and key not in seen:
                seen.add(key)
                metadata = known.get(route_id, {})
                mode_label = {
                    "angkot": "ANGKOT",
                    "damri": "BUS",
                    "kereta": "KERETA",
                    "jalan_kaki": "JALAN",
                }.get(mode, mode.upper())
                color_hex = (
                    step.get("color_hex") or metadata.get("route_color")
                )
                if not color_hex and mode == "jalan_kaki":
                    color_hex = "#707070"
                badges.append({
                    "mode_label": mode_label,
                    "route_id": route_id,
                    "route_code": (
                        step.get("route_code")
                        or metadata.get("route_code")
                        or route_id
                    ),
                    "route_name": metadata.get(
                        "route_name", step.get("route_name", "Trayek")
                    ),
                    "color_hex": color_hex,
                })
        return badges or [{
            "mode_label": "ANGKOT",
            "route_id": "Trayek",
            "route_name": "Bandung",
        }]

    def order_routes(self, routes):
        candidates = [dict(route) for route in routes]
        if not candidates:
            return []
        if len(candidates) < 2:
            for index, route in enumerate(candidates):
                route["display_name"] = "Rute tersedia"
                route["route_badges"] = self._route_badges(route)
                route["map_geometry"] = self.route_geometry(route)
            return candidates

        maximum_fare = max(route["fare_rupiah"] for route in candidates)
        minimum_fare = min(route["fare_rupiah"] for route in candidates)
        maximum_duration = max(route["duration_minutes"] for route in candidates)
        fastest = min(
            range(len(candidates)),
            key=lambda index: (
                candidates[index]["duration_minutes"],
                -candidates[index]["fare_rupiah"],
            ),
        )
        cheapest = min(
            range(len(candidates)),
            key=lambda index: (
                candidates[index]["fare_rupiah"],
                -candidates[index]["duration_minutes"],
            ),
        )
        remaining = [index for index in range(len(candidates)) if index not in (fastest, cheapest)]
        ordered_indices = [fastest]
        if remaining:
            balanced = min(
                remaining,
                key=lambda index: candidates[index]["duration_minutes"]
                + candidates[index]["fare_rupiah"] / 300.0,
            )
            ordered_indices.append(balanced)
            remaining.remove(balanced)
        if remaining:
            economical = min(
                remaining,
                key=lambda index: (
                    candidates[index]["fare_rupiah"],
                    candidates[index]["duration_minutes"],
                ),
            )
            ordered_indices.append(economical)
        if cheapest not in ordered_indices:
            ordered_indices.append(cheapest)
        for index in range(len(candidates)):
            if index not in ordered_indices:
                ordered_indices.append(index)

        def display_title(rank, route):
            if rank == 0:
                return "Tercepat / Mahal" if route["fare_rupiah"] == maximum_fare else "Tercepat"
            if rank == 3:
                if route["fare_rupiah"] != minimum_fare:
                    return "Alternatif Rute"
                return "Termurah / Lambat" if route["duration_minutes"] == maximum_duration else "Termurah"
            return self.ROUTE_TITLES[rank]

        ordered = []
        for rank, index in enumerate(ordered_indices[:4]):
            route = candidates[index]
            route["display_name"] = display_title(rank, route)
            route["route_badges"] = self._route_badges(route)
            route["map_geometry"] = self.route_geometry(route)
            ordered.append(route)
        return ordered

    def _schedule_auto_route(self, *_):
        if hasattr(self, "_route_trigger"):
            self._route_generation += 1
            self._route_trigger()

    @staticmethod
    def _minute_of_day(value):
        hhmm = EngineLoader.parse_hhmm(value)
        return hhmm // 100 * 60 + hhmm % 100

    @staticmethod
    def _format_minute_of_day(minutes):
        minutes %= 1440
        return "{:02d}:{:02d}".format(minutes // 60, minutes % 60)

    @staticmethod
    def _distance_km(first, second):
        lat1 = math.radians(first["lat"])
        lat2 = math.radians(second["lat"])
        delta_lat = lat2 - lat1
        delta_lon = math.radians(second["lon"] - first["lon"])
        value = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        )
        return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(value)))

    def _resolve_place(self, place):
        if place.source == "local":
            exact = self._stop_by_id(place.id)
            if exact is not None:
                return exact, 0.0, 0
        place_coordinates = {"lat": place.lat, "lon": place.lon}
        nearest = min(
            self.stops,
            key=lambda stop: self._distance_km(place_coordinates, stop),
        )
        distance = self._distance_km(place_coordinates, nearest)
        if distance > 20:
            raise LocationServiceError(
                "Lokasi {} berjarak {:.1f} km dari jaringan transit TrackSum."
                .format(place.name, distance)
            )
        walk_minutes = int(math.ceil(distance * 12)) if distance > 0.02 else 0
        return nearest, distance, walk_minutes

    def _add_access_steps(
        self, routes, origin, destination, origin_stop, destination_stop,
        origin_walk, destination_walk, user_departure,
    ):
        start_minutes = self._minute_of_day(user_departure)
        network_departure = start_minutes + origin_walk
        for route in routes:
            network_duration = route["duration_minutes"]
            network_arrival = network_departure + network_duration
            steps = list(route.get("steps", []))
            if origin_walk:
                steps.insert(0, {
                    "route_id": "WALK-ORIGIN",
                    "route_code": "WALK",
                    "route_name": "Jalan kaki ke transit",
                    "mode": "jalan_kaki",
                    "color_hex": "#707070",
                    "operator": "Jalan kaki",
                    "from": origin.name,
                    "to": origin_stop["name"],
                    "from_stop": origin.name,
                    "to_stop": origin_stop["name"],
                    "fare_rupiah": 0,
                    "wait_minutes": 0,
                    "duration_minutes": origin_walk,
                    "departure": self._format_minute_of_day(start_minutes),
                    "arrival": self._format_minute_of_day(network_departure),
                    "coordinates": [
                        {"lat": origin.lat, "lon": origin.lon},
                        {"lat": origin_stop["lat"], "lon": origin_stop["lon"]},
                    ],
                })
            if destination_walk:
                steps.append({
                    "route_id": "WALK-DESTINATION",
                    "route_code": "WALK",
                    "route_name": "Jalan kaki ke tujuan",
                    "mode": "jalan_kaki",
                    "color_hex": "#707070",
                    "operator": "Jalan kaki",
                    "from": destination_stop["name"],
                    "to": destination.name,
                    "from_stop": destination_stop["name"],
                    "to_stop": destination.name,
                    "fare_rupiah": 0,
                    "wait_minutes": 0,
                    "duration_minutes": destination_walk,
                    "departure": self._format_minute_of_day(network_arrival),
                    "arrival": self._format_minute_of_day(
                        network_arrival + destination_walk
                    ),
                    "coordinates": [
                        {"lat": destination_stop["lat"], "lon": destination_stop["lon"]},
                        {"lat": destination.lat, "lon": destination.lon},
                    ],
                })
            route["steps"] = steps
            route["departure"] = self._format_minute_of_day(start_minutes)
            route["duration_minutes"] = (
                origin_walk + network_duration + destination_walk
            )
            route["arrival"] = self._format_minute_of_day(
                start_minutes + route["duration_minutes"]
            )
        return routes

    def _start_route_search(self, _dt=0):
        if self.engine is None:
            self.route_status.text = getattr(
                self, "engine_error", "Library native tidak ditemukan."
            )
            return
        if self.start_place is None or self.goal_place is None:
            self.route_status.text = "Pilih titik awal dan tujuan terlebih dahulu."
            return

        self._route_generation += 1
        generation = self._route_generation
        try:
            departure = self.get_text(self.time_field)
            start_minutes = self._minute_of_day(departure)
            origin_stop, origin_distance, origin_walk = self._resolve_place(
                self.start_place
            )
            destination_stop, destination_distance, destination_walk = (
                self._resolve_place(self.goal_place)
            )
        except (LocationServiceError, ValueError) as exc:
            self.route_status.text = str(exc)
            return

        network_departure = self._format_minute_of_day(
            start_minutes + origin_walk
        )
        self.route_status.text = "Mencari rute transit..."

        def find_routes():
            with self._engine_lock:
                return self.engine.find_routes(
                    origin_stop["id"],
                    destination_stop["id"],
                    network_departure,
                )

        future = self.executor.submit(find_routes)

        def complete(done):
            def update(_dt):
                if generation != self._route_generation:
                    return
                try:
                    routes = done.result()
                    routes = self._add_access_steps(
                        routes,
                        self.start_place,
                        self.goal_place,
                        origin_stop,
                        destination_stop,
                        origin_walk,
                        destination_walk,
                        departure,
                    )
                    routes = self.order_routes(routes)
                except Exception as exc:
                    self.route_status.text = "Pencarian rute gagal: {}".format(exc)
                    self._clear_route_options()
                    return
                self.routes = routes
                self.route_list.clear_widgets()
                self.route_cards = []
                if not routes:
                    self.route_status.text = "Tidak ada rute transit yang tersedia."
                    self.map_panel.clear_route()
                    return
                if origin_distance > 0.02 or destination_distance > 0.02:
                    self.route_status.text = (
                        "Akses menggunakan halte terdekat; jalan kaki sekitar {} + {} mnt."
                        .format(origin_walk, destination_walk)
                    )
                else:
                    self.route_status.text = "Rute diperbarui otomatis."
                for index, route in enumerate(routes[:4]):
                    color = self.ROUTE_COLORS[index % len(self.ROUTE_COLORS)]
                    card = RouteOptionCard(
                        route,
                        color,
                        on_select=lambda i=index: self.select_route(i),
                    )
                    self.route_cards.append(card)
                    self.route_list.add_widget(card)
                self.select_route(0)

            Clock.schedule_once(update, 0)

        future.add_done_callback(complete)

    def _clear_route_options(self):
        self.routes = []
        self.route_cards = []
        self.route_list.clear_widgets()
        self.map_panel.clear_route()

    def search_routes(self):
        self._schedule_auto_route()

    def select_route(self, index):
        if not hasattr(self, "routes") or index >= len(self.routes):
            return
        route = self.routes[index]
        start = {"lat": self.start_place.lat, "lon": self.start_place.lon}
        goal = {"lat": self.goal_place.lat, "lon": self.goal_place.lon}
        self.map_panel.show_locations(start, goal)
        polyline = route.get("map_geometry") or route.get("polyline", [])
        color = self.ROUTE_COLORS[index % len(self.ROUTE_COLORS)]
        self.map_panel.show_route(polyline, color, route.get("map_segments"))
        self.selected_route = route
        self.selected_route_index = index
        for card_index, card in enumerate(self.route_cards):
            card.set_selected(card_index == index)

    def open_report_dialog(self):
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(16))
        kind = Spinner(
            text="Tarif",
            values=("Tarif", "Kondisi Jalan / Macet"),
            size_hint_y=None,
            height=dp(44),
        )
        route = TextInput(
            text=" / ".join(
                badge["route_id"]
                for badge in getattr(self, "selected_route", {}).get(
                    "route_badges", []
                )
            ),
            hint_text="Kode trayek",
            multiline=False,
            size_hint_y=None,
            height=dp(42),
        )
        text = TextInput(
            hint_text="Jelaskan perubahan tarif atau kondisi jalan",
            size_hint_y=None,
            height=dp(90),
        )
        photo = TextInput(
            hint_text="Path lengkap foto JPG/JPEG bukti (EXIF GPS wajib)",
            multiline=False,
            size_hint_y=None,
            height=dp(42),
        )
        content.add_widget(Label(
            text="Bukti foto wajib memiliki GPS dan waktu pengambilan.",
            color=PALETTE["muted"],
            size_hint_y=None,
            height=dp(28),
        ))
        for widget in (kind, route, text, photo):
            content.add_widget(widget)

        popup = Popup(
            title="Lapor Tarif / Kondisi Jalan",
            content=content,
            size_hint=(0.05, 0.05),
            opacity=0,
        )
        submit = TrackActionButton(
            text="Validasi & Kirim",
            size_hint_y=None,
            height=dp(44),
        )

        def submit_report(*_):
            try:
                save_report(
                    {"kind": kind.text, "route": route.text, "text": text.text},
                    photo.text,
                    ROOT / "data" / "crowdsource_reports.json",
                )
                popup.dismiss()
                self.show_popup(
                    "Laporan tersimpan",
                    "Foto berhasil divalidasi melalui metadata EXIF.",
                )
            except Exception as exc:
                self.show_popup("Validasi gagal", str(exc))

        submit.bind(on_press=submit_report)
        content.add_widget(submit)
        popup.open()
        Animation(
            size_hint_x=0.62,
            size_hint_y=0.72,
            opacity=1,
            duration=0.22,
            t="out_cubic",
        ).start(popup)

    def show_popup(self, title, message):
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(12))
        content.add_widget(Label(text=message, color=PALETTE["ink"]))
        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.05, 0.05),
            opacity=0,
        )
        close = TrackActionButton(text="Tutup", size_hint_y=None, height=dp(44))
        close.bind(on_press=lambda *_: popup.dismiss())
        content.add_widget(close)
        popup.open()
        Animation(
            size_hint_x=0.62,
            size_hint_y=0.38,
            opacity=1,
            duration=0.2,
            t="out_cubic",
        ).start(popup)


if __name__ == "__main__":
    TrackSumApp().run()
