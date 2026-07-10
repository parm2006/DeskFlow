import customtkinter as ctk
import logging
from app.server import DeskFlowServer
from app.client import DeskFlowClient

logger = logging.getLogger(__name__)

class DeskFlowGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("DeskFlow")
        self.geometry("400x350")
        
        self.server = None
        self.client = None
        
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
        
        self.server_start_btn = ctk.CTkButton(self.tab_server, text="Start Server", command=self.start_server)
        self.server_start_btn.pack(pady=10)
        
        # Client UI
        self.client_ip_label = ctk.CTkLabel(self.tab_client, text="Server IP:")
        self.client_ip_label.pack(pady=5)
        self.client_ip_entry = ctk.CTkEntry(self.tab_client)
        self.client_ip_entry.insert(0, "127.0.0.1")
        self.client_ip_entry.pack(pady=5)
        
        self.client_port_label = ctk.CTkLabel(self.tab_client, text="Port:")
        self.client_port_label.pack(pady=5)
        self.client_port_entry = ctk.CTkEntry(self.tab_client)
        self.client_port_entry.insert(0, "5000")
        self.client_port_entry.pack(pady=5)
        
        self.client_connect_btn = ctk.CTkButton(self.tab_client, text="Connect", command=self.connect_client)
        self.client_connect_btn.pack(pady=10)
        
        self.status_label = ctk.CTkLabel(self, text="Status: Idle", text_color="gray")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_server(self):
        port = int(self.server_port_entry.get())
        if self.server:
            self.server.stop()
            
        self.server = DeskFlowServer(port=port)
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
        
        if self.client:
            self.client.disconnect()
            
        self.client = DeskFlowClient()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.client.set_screen_size(screen_width, screen_height)
        
        if self.client.connect(ip, port):
            self.status_label.configure(text=f"Status: Connected to {ip}:{port}", text_color="green")
        else:
            self.status_label.configure(text="Status: Connection failed", text_color="red")

    def on_close(self):
        if self.server:
            self.server.stop()
        if self.client:
            self.client.disconnect()
        self.destroy()

def run_gui():
    ctk.set_appearance_mode("dark")
    app = DeskFlowGUI()
    app.mainloop()
