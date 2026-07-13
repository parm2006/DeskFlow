import customtkinter as ctk
import logging
import json
import os
import sys
import threading
from tkinter import messagebox
from app.server import DeskFlowServer
from app.client import DeskFlowClient
from app.file_transfer.toast import TransferToast
from app.global_hotkeys import GlobalHotkeyListener

logger = logging.getLogger(__name__)

KNOWN_HOSTS_FILE = "known_hosts.json"
SETTINGS_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DeskFlow", "settings.json")

class DeskFlowGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("DeskFlow")
        icon_root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__)))
        icon_path = os.path.join(icon_root, "assets", "DeskFlow.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
        self.geometry("310x560")
        self.resizable(False, False)
        
        self.server = None
        self.client = None
        self.known_hosts = self.load_known_hosts()
        self.settings = self.load_settings()
        self.overlay_center_x = self.winfo_screenwidth() // 2
        self.overlay_center_y = self.winfo_screenheight() // 2
        self.overlay = None
        self.overlay_active = False
        self.ui_hidden = False
        self._fingerprint_decisions = {}
        self._fingerprint_lock = threading.Lock()
        self.transfer_toast = TransferToast(self, self._cancel_transfer)
        
        # UI setup
        self.grid_columnconfigure(0, weight=1)
        
        # Tabs for Mode Selection
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tab_server = self.tabview.add("Server (Host)")
        self.tab_client = self.tabview.add("Client")
        
        # Server UI
        self.server_port_label = ctk.CTkLabel(self.tab_server, text="Port:")
        self.server_port_label.pack(pady=5)
        self.server_port_entry = ctk.CTkEntry(self.tab_server)
        self.server_port_entry.insert(0, "5000")
        self.server_port_entry.pack(pady=5)
        
        self.server_password_label = ctk.CTkLabel(self.tab_server, text="Password:")
        self.server_password_label.pack(pady=2)
        self.server_password_entry = ctk.CTkEntry(self.tab_server, show="*")
        self.server_password_entry.pack(pady=2)
        
        # Layout Selection
        self.layout_label = ctk.CTkLabel(self.tab_server, text="Client Position:")
        self.layout_label.pack(pady=5)
        
        self.layout_frame = ctk.CTkFrame(self.tab_server, fg_color="transparent")
        self.layout_frame.pack(pady=5)
        
        self.layout_btns = {}
        
        # Center server block
        self.server_btn = ctk.CTkButton(self.layout_frame, text="S", width=40, height=40, fg_color="#555555", state="disabled")
        self.server_btn.grid(row=1, column=1, padx=5, pady=5)
        
        def set_layout(pos):
            self.layout_position = pos
            for p, btn in self.layout_btns.items():
                if p == pos:
                    btn.configure(text="C", fg_color="white", text_color="black")
                else:
                    btn.configure(text="", fg_color="#333333")
                    
        self.layout_btns['top'] = ctk.CTkButton(self.layout_frame, text="", width=40, height=40, fg_color="#333333", command=lambda: set_layout('top'))
        self.layout_btns['top'].grid(row=0, column=1, padx=5, pady=5)
        
        self.layout_btns['left'] = ctk.CTkButton(self.layout_frame, text="", width=40, height=40, fg_color="#333333", command=lambda: set_layout('left'))
        self.layout_btns['left'].grid(row=1, column=0, padx=5, pady=5)
        
        self.layout_btns['right'] = ctk.CTkButton(self.layout_frame, text="C", width=40, height=40, fg_color="white", text_color="black", command=lambda: set_layout('right'))
        self.layout_btns['right'].grid(row=1, column=2, padx=5, pady=5)
        
        self.layout_btns['bottom'] = ctk.CTkButton(self.layout_frame, text="", width=40, height=40, fg_color="#333333", command=lambda: set_layout('bottom'))
        self.layout_btns['bottom'].grid(row=2, column=1, padx=5, pady=5)
        
        self.layout_position = 'right'
        
        self.server_start_btn = ctk.CTkButton(self.tab_server, text="Start Server", command=self.start_server)
        self.server_start_btn.pack(pady=10)
        self.server_stop_btn = ctk.CTkButton(self.tab_server, text="Stop Server", fg_color="red", hover_color="darkred", command=self.stop_server)
        
        # Client UI
        self.client_ip_label = ctk.CTkLabel(self.tab_client, text="Server IP:")
        self.client_ip_label.pack(pady=5)
        
        default_ip = self.known_hosts[0]['ip'] if self.known_hosts else "127.0.0.1"
        ip_list = [h['ip'] for h in self.known_hosts] if self.known_hosts else ["127.0.0.1"]
        
        self.client_ip_entry = ctk.CTkComboBox(self.tab_client, values=ip_list, command=self.on_ip_select)
        self.client_ip_entry.set(default_ip)
        self.client_ip_entry.pack(pady=5)
        
        self.client_port_label = ctk.CTkLabel(self.tab_client, text="Port:")
        self.client_port_label.pack(pady=5)
        self.client_port_entry = ctk.CTkEntry(self.tab_client)
        default_port = str(self.known_hosts[0]['port']) if self.known_hosts else "5000"
        self.client_port_entry.insert(0, default_port)
        self.client_port_entry.pack(pady=5)
        
        self.client_password_label = ctk.CTkLabel(self.tab_client, text="Password:")
        self.client_password_label.pack(pady=5)
        self.client_password_entry = ctk.CTkEntry(self.tab_client, show="*")
        self.client_password_entry.pack(pady=5)
        
        self.client_connect_btn = ctk.CTkButton(self.tab_client, text="Connect", command=self.connect_client)
        self.client_connect_btn.pack(pady=10)
        self.client_disconnect_btn = ctk.CTkButton(self.tab_client, text="Disconnect", fg_color="red", hover_color="darkred", command=self.disconnect_client)
        
        self.status_label = ctk.CTkLabel(self, text="Status: Idle", text_color="gray")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.global_hotkeys = GlobalHotkeyListener(
            on_background_toggle=lambda: self.after(0, self._toggle_ui_background),
            on_kill=lambda: self.after(0, self._emergency_exit_and_close),
        )
        self.global_hotkeys.start()
        # Restore the last role after both tabs have been created.
        self.tabview.set("Client" if self.settings.get("role") == "client" else "Server (Host)")

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_role(self, role):
        self.settings["role"] = role
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f)
        except OSError as e:
            logger.warning("Failed to save DeskFlow role: %s", e)

    def load_known_hosts(self):
        try:
            if os.path.exists(KNOWN_HOSTS_FILE):
                with open(KNOWN_HOSTS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load known hosts: {e}")
        return []

    def save_known_host(self, ip, port):
        # Remove if it already exists to move it to the top
        self.known_hosts = [h for h in self.known_hosts if h['ip'] != ip or h['port'] != port]
        self.known_hosts.insert(0, {'ip': ip, 'port': port})
        # Keep only the last 10
        self.known_hosts = self.known_hosts[:10]
        
        try:
            with open(KNOWN_HOSTS_FILE, 'w') as f:
                json.dump(self.known_hosts, f)
            # Update combo box values
            self.client_ip_entry.configure(values=[h['ip'] for h in self.known_hosts])
        except Exception as e:
            logger.error(f"Failed to save known host: {e}")

    def on_ip_select(self, choice):
        for host in self.known_hosts:
            if host['ip'] == choice:
                self.client_port_entry.delete(0, 'end')
                self.client_port_entry.insert(0, str(host['port']))
                break

    def start_server(self):
        self.save_role("server")
        port = int(self.server_port_entry.get())
        password = self.server_password_entry.get()
        
        if not password:
            self.status_label.configure(text="Status: Error - Password required", text_color="red")
            return
        if self.server:
            self.server.stop()
            
        if not self.overlay:
            self._init_overlay()
            
        self.server = DeskFlowServer(
            password=password, 
            port=port, 
            layout_position=self.layout_position,
            on_capture_start=self.show_overlay, 
            on_capture_stop=self.hide_overlay,
            on_transfer_status=self._on_transfer_status,
        )
        self.server.control_network.register_callback('connected', self._on_server_client_connected)
        self.server.control_network.register_callback('disconnected', self._on_server_client_disconnected)
        self.server.on_ui_visibility_changed = self._apply_remote_ui_visibility
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.server.set_screen_size(screen_width, screen_height)
        
        if self.server.start():
            self.status_label.configure(text=f"Status: Server Listening on port {port}", text_color="green")
            self.server_start_btn.pack_forget()
            self.server_stop_btn.pack(pady=10)
        else:
            self.status_label.configure(text="Status: Failed to start server", text_color="red")

    def connect_client(self):
        self.save_role("client")
        ip = self.client_ip_entry.get()
        port = int(self.client_port_entry.get())
        password = self.client_password_entry.get()
        
        if not password:
            self.status_label.configure(text="Status: Error - Password required", text_color="red")
            return
        
        if self.client:
            self.client.disconnect()
            
        self.client = DeskFlowClient(
            password=password,
            on_transfer_status=self._on_transfer_status,
            fingerprint_approval=self._approve_peer_fingerprint,
        )
        self.client.on_ui_visibility_changed = self._apply_remote_ui_visibility
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.client.set_screen_size(screen_width, screen_height)
        
        self.status_label.configure(text=f"Status: Connecting to {ip}:{port}...", text_color="orange")
        self.client_connect_btn.configure(state="disabled")
        
        def _on_connect_result(success, error_msg):
            # This is called from a background thread, use after() to update GUI safely
            self.after(0, lambda: self._handle_connect_result(success, error_msg, ip, port))
            
        self.client.connect(ip, port, _on_connect_result)

    def _approve_peer_fingerprint(self, fingerprint, host):
        """Ask on the UI thread before trusting a new peer identity.

        NetworkClient invokes this callback from a connection worker.  The
        event bridges that worker to Tk's main loop and also coalesces the
        control/data lane prompts into one decision.
        """
        key = (host, fingerprint)
        with self._fingerprint_lock:
            if key in self._fingerprint_decisions:
                return self._fingerprint_decisions[key]
            decision = {}
            done = threading.Event()

            def prompt():
                try:
                    short = fingerprint.upper()
                    approved = messagebox.askyesno(
                        "Approve DeskFlow peer?",
                        f"A new DeskFlow peer was found at {host}.\n\n"
                        f"Certificate fingerprint:\n{short}\n\n"
                        "Approve this computer and remember its identity?",
                        parent=self,
                    )
                    decision["value"] = bool(approved)
                finally:
                    done.set()

            self.after(0, prompt)
            # Release the lock while waiting so a reconnect can inspect state.
        done.wait()
        result = decision.get("value", False)
        with self._fingerprint_lock:
            self._fingerprint_decisions[key] = result
        return result

    def _handle_connect_result(self, success, error_msg, ip, port):
        self.client_connect_btn.configure(state="normal")
        if success:
            self.status_label.configure(text=f"Status: Connected to {ip}:{port}", text_color="green")
            self.save_known_host(ip, port)
            self.client_connect_btn.pack_forget()
            self.client_disconnect_btn.pack(pady=10)
            self.client.control_network.register_callback('disconnected', self._on_client_disconnected_event)
        else:
            self.status_label.configure(text=f"Status: Connection failed ({error_msg})", text_color="red")

    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
        self.server_stop_btn.pack_forget()
        self.server_start_btn.pack(pady=10)
        self.status_label.configure(text="Status: Server stopped", text_color="gray")

    def disconnect_client(self):
        if self.client:
            self.client.disconnect()
            self.client = None
        self.client_disconnect_btn.pack_forget()
        self.client_connect_btn.pack(pady=10)
        self.status_label.configure(text="Status: Disconnected", text_color="gray")

    def _on_server_client_connected(self, data):
        self.after(0, lambda: self.status_label.configure(text="Status: Client Connected!", text_color="green"))
        
    def _on_server_client_disconnected(self, data):
        if self.server:
            port = self.server_port_entry.get()
            self.after(0, lambda: self.status_label.configure(text=f"Status: Server Listening on port {port}", text_color="green"))

    def _on_client_disconnected_event(self, data):
        self.after(0, self.disconnect_client)

    def _on_transfer_status(self, status):
        self.after(0, lambda: self.transfer_toast.show(status))

    def set_ui_background(self, hidden):
        """Apply local visibility and ask the peer to do the same."""
        self._apply_remote_ui_visibility(hidden)
        peer = self.server if self.server is not None else self.client
        if peer is not None:
            try:
                peer.set_ui_visibility(hidden)
            except Exception:
                logger.debug("Peer UI visibility update failed", exc_info=True)

    def _toggle_ui_background(self):
        self.set_ui_background(not self.ui_hidden)

    def _emergency_exit_and_close(self):
        if self.server:
            self.server.emergency_exit()
        self.on_close()

    def _apply_remote_ui_visibility(self, hidden):
        def apply():
            self.ui_hidden = bool(hidden)
            if hidden:
                self.withdraw()
            else:
                self.deiconify()
                self.lift()
                self.focus_force()
        self.after(0, apply)

    def _cancel_transfer(self, job_id):
        if self.server and self.server.transfer_controller.status(job_id):
            return self.server.cancel_transfer(job_id)
        if self.client and self.client.transfer_controller.status(job_id):
            return self.client.cancel_transfer(job_id)
        return False

    def on_close(self):
        if hasattr(self, "global_hotkeys"):
            self.global_hotkeys.stop()
        if self.overlay:
            self.hide_overlay()
        if self.server:
            self.server.stop()
        if self.client:
            self.client.disconnect()
        self.destroy()

    def _init_overlay(self):
        from app.input_geometry import windows_work_area, work_area_geometry

        self.overlay = ctk.CTkToplevel(self)
        left, top, right, bottom = windows_work_area()
        self.overlay.geometry(work_area_geometry((left, top, right, bottom)))
        self.overlay.overrideredirect(True)
        self.overlay_center_x = (right - left) // 2
        self.overlay_center_y = (bottom - top) // 2
        self.overlay.attributes("-alpha", 0.01) # Almost invisible
        self.overlay.config(cursor="none") # Hide host cursor
        self.overlay.attributes("-topmost", True)
        
        # Bind events
        self.overlay.bind("<Motion>", self.on_overlay_motion)
        self.overlay.bind("<ButtonPress>", self.on_overlay_press)
        self.overlay.bind("<ButtonRelease>", self.on_overlay_release)
        self.overlay.bind("<MouseWheel>", self.on_overlay_scroll)
        self.overlay.bind("<FocusOut>", self.on_overlay_focus_out)
        
        self.overlay.withdraw() # Hide it initially
        self.last_x = self.overlay_center_x
        self.last_y = self.overlay_center_y
        self.warp_count = 0

    def show_overlay(self):
        def _show():
            if self.overlay:
                self.overlay_active = True
                self.overlay.deiconify() # Show it
                self.overlay.focus_force()
                self.overlay.grab_set()
                self.transfer_toast.raise_if_visible()
                
                # Initial position
                self.last_x = self.overlay_center_x
                self.last_y = self.overlay_center_y
                self.overlay.event_generate('<Motion>', warp=True, x=self.overlay_center_x, y=self.overlay_center_y)
        self.after(0, _show)

    def hide_overlay(self):
        def _hide():
            if self.overlay:
                self.overlay_active = False
                self.overlay.grab_release()
                self.overlay.withdraw()
        self.after(0, _hide)

    def on_overlay_motion(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        
        # Flawless warp artifact filter: 
        # A jump of > 50 pixels is impossible for normal mouse movement in a few ms.
        # This perfectly filters out the -100px jump caused by the warp below!
        if abs(dx) > 50 or abs(dy) > 50:
            self.last_x = event.x
            self.last_y = event.y
            return
            
        if dx != 0 or dy != 0:
            if self.server:
                self.server.on_mouse_move(dx, dy)
                
            # If we get too close to the edges of the overlay, re-center the mouse 
            if abs(event.x - self.overlay_center_x) > 100 or abs(event.y - self.overlay_center_y) > 100:
                self.overlay.event_generate('<Motion>', warp=True, x=self.overlay_center_x, y=self.overlay_center_y)
                
            self.last_x = event.x
            self.last_y = event.y

    def on_overlay_press(self, event):
        if not self.server: return
        button_map = {1: 'left', 2: 'middle', 3: 'right'}
        btn = button_map.get(event.num)
        if btn:
            self.server.on_mouse_click(btn, True)

    def on_overlay_release(self, event):
        if not self.server: return
        button_map = {1: 'left', 2: 'middle', 3: 'right'}
        btn = button_map.get(event.num)
        if btn:
            self.server.on_mouse_click(btn, False)

    def on_overlay_scroll(self, event):
        if not self.server: return
        # Windows Tkinter reports scroll in event.delta (usually multiples of 120)
        dy = 1 if event.delta > 0 else -1
        self.server.on_mouse_scroll(0, dy)

    def on_overlay_focus_out(self, event):
        # If the user opens the Snipping Tool (Win+Shift+S) or Alt-Tabs natively,
        # the overlay loses focus. We MUST return the cursor to the Server automatically.
        if self.overlay_active and self.server and self.server.control_connected:
            logger.info("Overlay lost focus (e.g. Snipping Tool). Switching back to Server.")
            self.server.on_switch_back({'ratio': 0.5})

def run_gui():
    import ctypes
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE ensures winfo_screenheight matches pynput physical pixels
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
        
    ctk.set_appearance_mode("dark")
    app = DeskFlowGUI()
    app.mainloop()
