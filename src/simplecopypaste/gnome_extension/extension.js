// SimpleCopyPaste Shell - the GNOME companion for the SimpleCopyPaste clipboard tool.
//
// GNOME Wayland does not let applications read the global pointer position,
// synthesize keystrokes, or add a top-bar icon, so this extension provides
// all three:
//
//   * GetPointer — where the cursor is, so the popup opens at the mouse.
//   * Paste      — a Ctrl+V (or other combo) so picking a clip pastes it,
//                  with no need for ydotool or any extra permission.
//   * a panel indicator whose left click opens the clip records.
//
// It only acts when the user asks for it.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.simplecopypaste.Shell">
    <method name="GetPointer">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
    </method>
    <method name="Paste">
      <arg type="s" direction="in" name="combo"/>
      <arg type="b" direction="in" name="dry"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="Ping">
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="SetClickWatch">
      <arg type="b" direction="in" name="on"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <!-- "the user went elsewhere": close the panel. Renamed from Clicked,
         which no longer described it once focus changes counted too. -->
    <signal name="Dismiss"/>
    <signal name="Clicked"/>
  </interface>
</node>`;

const OBJECT_PATH = '/org/simplecopypaste/Shell';
const CLI = 'simplecopypaste';

// WM_CLASS of our windows, used to tell our own popup from other windows.
const WM_CLASS = 'simplecopypaste';

const MODIFIERS = {
    ctrl: 'KEY_Control_L',
    control: 'KEY_Control_L',
    shift: 'KEY_Shift_L',
    alt: 'KEY_Alt_L',
    super: 'KEY_Super_L',
    meta: 'KEY_Super_L',
};

const KEYS = {
    v: 'KEY_v',
    c: 'KEY_c',
    insert: 'KEY_Insert',
    ins: 'KEY_Insert',
};

// Panel icons take the bar's foreground colour, which on a dark bar is pure
// white and reads harsher than the neighbouring tray icons. Dim ours a little
// by lowering the actor's opacity: unlike a fixed grey, this also does the
// right thing on a light bar, where it softens the black instead.
const ICON_OPACITY = 0.82;

// PanelMenu.Button toggles its menu from vfunc_event, which runs *before*
// any handler attached with connect(). Intercepting the primary button in a
// subclass is the only way to keep the menu closed on a left click.
const Indicator = GObject.registerClass(
class SimpleCopyPasteIndicator extends PanelMenu.Button {
    _init(nameText, onPrimary) {
        super._init(0.5, nameText, false);
        this._onPrimary = onPrimary;
    }

    vfunc_event(event) {
        if (event.type() === Clutter.EventType.BUTTON_PRESS &&
            event.get_button() === Clutter.BUTTON_PRIMARY) {
            this._onPrimary();
            return Clutter.EVENT_STOP;
        }
        return super.vfunc_event(event);  // right click: open the menu
    }
});

export default class SimpleCopyPasteShellExtension extends Extension {
    enable() {
        this._device = null;
        this._clickWatch = false;

        this._object = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._object.export(Gio.DBus.session, OBJECT_PATH);

        // Clicks that land on surfaces the shell owns (the desktop, the top
        // bar) never reach the app, and they do not move keyboard focus
        // either, so a popup cannot notice them by watching for focus loss.
        // The stage sees them, so report them while a popup is open.
        this._stageId = global.stage.connect('captured-event', (_stage, event) => {
            if (this._clickWatch &&
                event.type() === Clutter.EventType.BUTTON_PRESS)
                this._dismiss('click on the shell');
            return Clutter.EVENT_PROPAGATE;
        });

        // Clicking another window is the other case the app cannot see: the
        // popup never takes keyboard focus (XWayland keeps it following the
        // pointer), so nothing is lost and no focus-out arrives. The
        // compositor knows which window is focused, so watch that instead.
        this._focusId = global.display.connect('notify::focus-window', () => {
            if (!this._clickWatch)
                return;
            const focused = global.display.focus_window;
            if (focused && focused.get_wm_class() === WM_CLASS)
                return;  // focus moved to our own popup, not away from it
            this._dismiss('focus moved to another window');
        });

        this._buildIndicator();
    }

    _dismiss(reason) {
        log(`SimpleCopyPaste: dismiss (${reason})`);
        this._object.emit_signal('Dismiss', null);
    }

    // Called by the app while a popup is on screen.
    SetClickWatch(on) {
        this._clickWatch = Boolean(on);
        return true;
    }

    // -------------------------------------------------------- panel icon

    _buildIndicator() {
        // Left click opens the clip records, the same thing the keyboard
        // shortcut does; the settings live in the menu, on the right button.
        // The Indicator subclass keeps the two apart.
        this._indicator = new Indicator(this.metadata.name, () => this._run('toggle'));
        this._indicator.add_child(this._panelIcon());

        this._indicator.menu.addAction('Open clipboard', () => this._run('toggle'));
        this._indicator.menu.addAction('Settings', () => this._run('settings'));

        Main.panel.addToStatusArea(
            this.uuid, this._indicator, 1, this._panelPosition());
    }

    _panelPosition() {
        // Sit with the tray icons (Docker, VPN, ...), wherever the
        // AppIndicator extension has been told to put them.
        try {
            const settings = new Gio.Settings({
                schema_id: 'org.gnome.shell.extensions.appindicator',
            });
            const position = settings.get_string('tray-pos');
            if (['left', 'center', 'right'].includes(position))
                return position;
        } catch (error) {
            // Schema not installed: fall back to the conventional side.
        }
        return 'right';
    }

    _panelIcon() {
        // The panel asks for symbolic icons and recolours them itself, so the
        // mark follows a light or dark top bar. That only works when the icon
        // is loaded *by name* from the icon theme, which is why the symbolic
        // one is installed there and preferred here. The extra class turns up
        // its size in stylesheet.css: at the theme's default it is too small
        // to read.
        let gicon;
        if (this._symbolicInstalled()) {
            gicon = Gio.icon_new_for_string('simplecopypaste-symbolic');
        } else {
            // Fallback: a ready-coloured PNG shipped inside the extension.
            const bundled = this.dir.get_child('panel.png');
            if (bundled.query_exists(null))
                gicon = Gio.icon_new_for_string(bundled.get_path());
            else
                gicon = Gio.icon_new_for_string('simplecopypaste');
        }
        const icon = new St.Icon({
            gicon,
            style_class: 'system-status-icon simplecopypaste-panel-icon',
        });
        icon.opacity = Math.round(ICON_OPACITY * 255);
        return icon;
    }

    _symbolicInstalled() {
        const name = 'simplecopypaste-symbolic.svg';
        const dirs = GLib.get_system_data_dirs().concat([GLib.get_user_data_dir()]);
        return dirs.some((dir) => {
            const path = GLib.build_filenamev(
                [dir, 'icons', 'hicolor', 'symbolic', 'apps', name]);
            return Gio.File.new_for_path(path).query_exists(null);
        });
    }

    _run(command) {
        try {
            GLib.spawn_async(
                null,
                [CLI, command],
                null,
                GLib.SpawnFlags.SEARCH_PATH,
                null
            );
        } catch (error) {
            logError(error, `SimpleCopyPaste: could not run '${CLI} ${command}'`);
        }
    }

    // ------------------------------------------------------- D-Bus API

    GetPointer() {
        const [x, y] = global.get_pointer();
        return [Math.round(x), Math.round(y)];
    }

    Ping() {
        return true;
    }

    // Parses "ctrl+shift+v" into [keysym, ...]; null when unsupported.
    _parse(combo) {
        const parts = String(combo || '')
            .toLowerCase()
            .split('+')
            .map((part) => part.trim())
            .filter((part) => part.length > 0);
        if (parts.length === 0)
            return null;

        const key = parts[parts.length - 1];
        const keyName = KEYS[key];
        if (!keyName)
            return null;

        const keysyms = [];
        for (const part of parts.slice(0, -1)) {
            const modName = MODIFIERS[part];
            if (!modName)
                return null;  // unknown modifier: refuse rather than guess
            keysyms.push(Clutter[modName]);
        }
        keysyms.push(Clutter[keyName]);
        if (keysyms.some((k) => k === undefined))
            return null;
        return keysyms;
    }

    Paste(combo, dry) {
        const keysyms = this._parse(combo);
        if (keysyms === null)
            return false;
        if (dry)
            return true;  // validate the combo without touching input

        try {
            const seat = Clutter.get_default_backend().get_default_seat();
            if (!this._device)
                this._device = seat.create_virtual_device(Clutter.VirtualDeviceType.KEYBOARD);
            const time = Clutter.get_current_event_time();
            for (const keysym of keysyms)
                this._device.notify_keyval(time, keysym, Clutter.KeyState.PRESSED);
            for (const sym of [...keysyms].reverse())
                this._device.notify_keyval(time, sym, Clutter.KeyState.RELEASED);
            return true;
        } catch (error) {
            logError(error, 'SimpleCopyPaste: could not synthesize the paste shortcut');
            this._device = null;
            return false;
        }
    }

    disable() {
        this._device = null;
        this._clickWatch = false;

        if (this._stageId) {
            global.stage.disconnect(this._stageId);
            this._stageId = 0;
        }
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
        if (this._object) {
            this._object.unexport();
            this._object = null;
        }
    }
}
