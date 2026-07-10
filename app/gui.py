import customtkinter as ctk
import logging
import json
import os
from app.server import DeskFlowServer
from app.client import DeskFlowClient

logger = logging.getLogger(__name__)

KNOWN_HOSTS_FILE = "known_hosts.json"

class DeskFlowGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("DeskFlow")
        self.geometry("400x450")
        
        self.server = None
        self.client = None
        self.known_hosts = self.load_known_hosts()
        self.overlay_center_x = self.winfo_screenwidth() // 2
        self.overlay_center_y = self.winfo_screenheight() // 2
        self._init_overlay()
        
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
        self.server_password_label.pack(pady=5)
        self.server_password_entry = ctk.CTkEntry(self.tab_server, show="*")
        self.server_password_entry.insert(0, "deskflow123")
        self.server_password_entry.pack(pady=5)
        
        self.server_start_btn = ctk.CTkButton(self.tab_server, text="Start Server", command=self.start_server)
        self.server_start_btn.pack(pady=10)
        
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
        self.client_password_entry.insert(0, "deskflow123")
        self.client_password_entry.pack(pady=5)
        
        self.client_connect_btn = ctk.CTkButton(self.tab_client, text="Connect", command=self.connect_client)
        self.client_connect_btn.pack(pady=10)
        
        self.status_label = ctk.CTkLabel(self, text="Status: Idle", text_color="gray")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)

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
        port = int(self.server_port_entry.get())
        password = self.server_password_entry.get()
        if self.server:
            self.server.stop()
            
        self.server = DeskFlowServer(password=password, port=port, on_capture_start=self.show_overlay, on_capture_stop=self.hide_overlay)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.server.set_screen_size(screen_width, screen_height)
        
        if self.server.start():
            self.status_label.configure(text=f"Status: Server Listening on port {port}", text_color="green")
        else:
            self.status_label.configure(text="Status: Failed to start server", text_color="red")

    def connect_client(self):
        ip = self.client_ip_entry.get()
        port = int(self.client_port_entry.get())
        password = self.client_password_entry.get()
        
        if self.client:
            self.client.disconnect()
            
        self.client = DeskFlowClient(password=password)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.client.set_screen_size(screen_width, screen_height)
        
        if self.client.connect(ip, port):
            self.status_label.configure(text=f"Status: Connected to {ip}:{port}", text_color="green")
            self.save_known_host(ip, port)
        else:
            self.status_label.configure(text="Status: Connection failed", text_color="red")

    def on_close(self):
        self.hide_overlay()
        if self.server:
            self.server.stop()
        if self.client:
            self.client.disconnect()
        self.destroy()

    def _init_overlay(self):
        self.overlay = ctk.CTkToplevel(self)
        self.overlay.attributes("-fullscreen", True)
        self.overlay.attributes("-alpha", 0.01) # Almost invisible
        self.overlay.config(cursor="none") # Hide host cursor
        self.overlay.attributes("-topmost", True)
        
        # Bind events
        self.overlay.bind("<Motion>", self.on_overlay_motion)
        self.overlay.bind("<ButtonPress>", self.on_overlay_press)
        self.overlay.bind("<ButtonRelease>", self.on_overlay_release)
        self.overlay.bind("<MouseWheel>", self.on_overlay_scroll)
        
        self.overlay.withdraw() # Hide it initially
        self.last_x = self.overlay_center_x
        self.last_y = self.overlay_center_y
        self.warp_count = 0

    def show_overlay(self):
        self.overlay.deiconify() # Show it
        self.overlay.focus_force()
        self.overlay.grab_set()
        
        # Initial position
        self.last_x = self.overlay_center_x
        self.last_y = self.overlay_center_y
        self.overlay.event_generate('<Motion>', warp=True, x=self.overlay_center_x, y=self.overlay_center_y)

    def hide_overlay(self):
        self.overlay.grab_release()
        self.overlay.withdraw()

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
