import time
import logging
import signal
import traceback
import Xlib
import Xlib.display
import re
from subprocess import run, PIPE
from contextlib import contextmanager
from systemd.journal import JournalHandler

journald = JournalHandler()
fmt = logging.Formatter("[%(levelname)s] %(message)s")
journald.setFormatter(fmt)

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
logger.addHandler(journald)

# console = logging.StreamHandler()
# console.setFormatter(fmt)
# logger.addHandler(console)

XCAPE_CODES = (
    "Control_L=Escape;"
    "Control_R=Return;"
    "Super_L=Tab;"
    "Super_R=backslash;"
    "Alt_R=space;"
    "ISO_Level3_Shift=XF86Search"
)


class XcapeManager:
    def __init__(self):
        self.disp = Xlib.display.Display()
        self.root = self.disp.screen().root
        self.layout = self._get_layout()
        self.active = False

        logger.debug("current layout: " + self.layout)

        self.NET_ACTIVE_WINDOW = self.disp.intern_atom("_NET_ACTIVE_WINDOW")
        self.NET_WM_NAME = self.disp.intern_atom("_NET_WM_NAME")  # UTF-8
        self.WM_NAME = self.disp.intern_atom("WM_NAME")  # Legacy encoding

        self.last_seen = {"xid": None, "title": None}

        self._activate_xcape_layer(self._using_hypermode())

        # wait for an active window to appear
        while not self.root.get_full_property(
            self.NET_ACTIVE_WINDOW, Xlib.X.AnyPropertyType
        ):
            logger.debug("waiting for window")
            time.sleep(0.5)

        logger.info("active window found")

        # need to set this to get property events
        # in this case the root window is being set, so every window is
        # affected
        # by default no events are passed to clients
        self.root.change_attributes(event_mask=Xlib.X.PropertyChangeMask)

        self._get_window_name(self._get_active_window()[0])
        self._handle_change(self.last_seen)

    def wait(self):
        logger.debug("starting loop")
        while True:
            self._handle_xevent()
            logger.debug("handled event")

    def kill(self):
        pass

    def _get_layout(self):
        res = run(["setxkbmap", "-query"], stdout=PIPE)
        res = res.stdout.decode("utf-8")
        res = re.search("layout:\s+(.*)\n", res).group(1)
        return res

    def _handle_xevent(self):
        # blocks until we get an event
        event = self.disp.next_event()

        # detect layout changes
        if event.type == Xlib.X.MappingNotify and event.request == 1:
            logger.debug("layout change requested")
            if self.layout != self._get_layout():
                self.layout = self._get_layout()
                logger.debug("changing layout to " + self.layout)
                self._activate_xcape_layer()
            return

        # why not listen to focus in/out events?
        if event.type != Xlib.X.PropertyNotify:
            return

        changed = False
        if event.atom == self.NET_ACTIVE_WINDOW:
            if self._get_active_window()[1]:
                changed = changed or self._get_window_name(self.last_seen["xid"])[1]
        elif event.atom in (self.NET_WM_NAME, self.WM_NAME):
            changed = changed or self._get_window_name(self.last_seen["xid"])[1]

        if changed:
            self._handle_change(self.last_seen)

    def _get_active_window(self):
        win_id = self.root.get_full_property(
            self.NET_ACTIVE_WINDOW, Xlib.X.AnyPropertyType
        ).value[0]

        focus_changed = win_id != self.last_seen["xid"]
        if focus_changed:
            with self._window_obj(self.last_seen["xid"]) as old_win:
                if old_win:
                    old_win.change_attributes(event_mask=Xlib.X.NoEventMask)

            self.last_seen["xid"] = win_id
            with self._window_obj(win_id) as new_win:
                if new_win:
                    new_win.change_attributes(event_mask=Xlib.X.PropertyChangeMask)

        return win_id, focus_changed

    @contextmanager
    def _window_obj(self, win_id):
        window_obj = None
        if win_id:
            try:
                window_obj = self.disp.create_resource_object("window", win_id)
            except Xlib.error.XError:
                pass
        yield window_obj

    def _get_window_name_inner(self, win_obj):
        for atom in (self.NET_WM_NAME, self.WM_NAME):
            try:
                window_name = win_obj.get_full_property(atom, 0)
            # Apparently a Debian distro package bug
            # Sometimes transitions trigger badvalue or badwindow errors
            # I shall assume (for now) that these are not valid windows
            # and can be ignored
            except (UnicodeDecodeError, Xlib.error.BadValue, Xlib.error.BadWindow):
                title = "<could not decode characters>"
            else:
                if window_name:
                    win_name = window_name.value
                    if isinstance(win_name, bytes):
                        # Apparently COMPOUND_TEXT is so arcane that this is how
                        # tools like xprop deal with receiving it these days
                        win_name = win_name.decode("latin1", "replace")
                    return win_name
                else:
                    title = "<unnamed window>"

        return "{} (XID: {})".format(title, win_obj.id)

    def _get_window_name(self, win_id):
        if not win_id:
            self.last_seen["title"] = "<no window id>"
            return self.last_seen["title"]

        title_changed = False
        with self._window_obj(win_id) as wobj:
            if wobj:
                win_title = self._get_window_name_inner(wobj)
                title_changed = win_title != self.last_seen["title"]
                self.last_seen["title"] = win_title

        return self.last_seen["title"], title_changed

    def _activate_xcape_layer(self, on=True):
        print(on)
        if on == self.active:
            return

        if self._using_hypermode() and on:
            self.active = True
            run(["killall", "xcape"])
            run(["xcape", "-t", "500", "-e", XCAPE_CODES])
        else:
            self.active = False
            run(["killall", "xcape"])

    def _handle_change(self, new_state):
        title = new_state["title"]
        if title == "VirtualBox" or (
            "Oracle VM VirtualBox" in title
            and "Oracle VM VirtualBox Manager" not in title
        ):
            # ("VMware Workstation" in title and \
            #  title != "Home - VMware Workstation"):
            self._activate_xcape_layer(False)
        else:
            self._activate_xcape_layer(True)

    def _using_hypermode(self):
        return self.layout == "hypermode"


def clean():
    run(["killall" "xcape"])


def sigterm_handler(signum, stackFrame):
    logger.info("Caught SIGTERM")
    raise SystemExit


# if __name__ == "__main__":
def main():
    # we make the assumption that this script will be started
    # from within X, therefore it only needs to know if there
    # are windows present (and not test for X server running)
    try:
        logger.info("starting")
        signal.signal(signal.SIGTERM, sigterm_handler)

        xman = XcapeManager()
        xman.wait()
    except Exception:
        logger.critical(traceback.format_exc())
    finally:
        clean()
