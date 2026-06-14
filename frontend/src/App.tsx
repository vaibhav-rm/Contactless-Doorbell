import React, { useState, useEffect, useRef } from 'react';
import { 
  Shield, 
  ShieldAlert, 
  Lock, 
  Unlock, 
  Users, 
  History, 
  Activity, 
  Camera, 
  Check, 
  X, 
  Plus, 
  Trash2, 
  RefreshCw, 
  Wifi, 
  Cpu, 
  HardDrive, 
  Thermometer, 
  Clock, 
  Download, 
  Sliders, 
  UserCheck
} from 'lucide-react';

// API Configuration
const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
const API_BASE = `http://${hostname}:8080/api`;
const WS_URL = `ws://${hostname}:8080/ws/doorbell`;
const STATIC_BASE = `http://${hostname}:8080`;

interface User {
  id: number;
  name: String;
  role: String;
  imagePath: String;
  createdAt: String;
}

interface AccessLog {
  id: number;
  timestamp: String;
  imagePath: String;
  recognitionResult: String;
  decision: String;
  approvedBy: String;
}

interface SystemMetrics {
  cpuUsage: number;
  memoryUsage: number;
  temperature: number;
  uptime: String;
  status: String;
  network: String;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'logs' | 'users' | 'simulator'>('dashboard');
  const [isLocked, setIsLocked] = useState(true);
  const [users, setUsers] = useState<User[]>([]);
  const [logs, setLogs] = useState<AccessLog[]>([]);
  const [recentLogs, setRecentLogs] = useState<AccessLog[]>([]);
  const [metrics, setMetrics] = useState<SystemMetrics>({
    cpuUsage: 12.5,
    memoryUsage: 45.2,
    temperature: 41.2,
    uptime: '0h 0m 0s',
    status: 'connecting',
    network: 'Checking...'
  });
  
  // Pending approvals list
  const [pendingAlerts, setPendingAlerts] = useState<AccessLog[]>([]);
  
  // Form state
  const [newUserName, setNewUserName] = useState('');
  const [newUserRole, setNewUserRole] = useState('RESIDENT');
  const [newUserImage, setNewUserImage] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Connection State
  const [wsStatus, setWsStatus] = useState<'connected' | 'disconnected' | 'connecting'>('connecting');
  const wsRef = useRef<WebSocket | null>(null);

  // Simulator values
  const [simOledText, setSimOledText] = useState('SYSTEM LOCKED\nREADY');
  const [simServoAngle, setSimServoAngle] = useState(0);

  // Fetch initial data
  const fetchData = async () => {
    try {
      // Fetch lock status
      const lockRes = await fetch(`${API_BASE}/lock/status`);
      if (lockRes.ok) {
        const data = await lockRes.json();
        setIsLocked(data.locked);
        setSimServoAngle(data.locked ? 0 : 90);
        setSimOledText(data.locked ? "SYSTEM LOCKED\nREADY" : "DOOR UNLOCKED\nWELCOME");
      }

      // Fetch users
      const usersRes = await fetch(`${API_BASE}/users`);
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data);
      }

      // Fetch logs
      const logsRes = await fetch(`${API_BASE}/visitors/logs`);
      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(data);
        
        // Find pending logs to put into alerts
        const pending = data.filter((l: AccessLog) => l.decision === 'PENDING');
        setPendingAlerts(pending);
      }

      // Fetch recent logs
      const recentRes = await fetch(`${API_BASE}/visitors/logs/recent`);
      if (recentRes.ok) {
        const data = await recentRes.json();
        setRecentLogs(data);
      }

      // Fetch metrics
      const statusRes = await fetch(`${API_BASE}/status`);
      if (statusRes.ok) {
        const data = await statusRes.json();
        setMetrics(data);
      }
    } catch (err) {
      console.error("Error fetching initialization data:", err);
    }
  };

  // Periodic metrics polling
  useEffect(() => {
    fetchData();
    const interval = setInterval(async () => {
      try {
        const statusRes = await fetch(`${API_BASE}/status`);
        if (statusRes.ok) {
          const data = await statusRes.json();
          setMetrics(data);
        }
      } catch (err) {
        console.error("Error polling metrics:", err);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // WebSockets setup
  useEffect(() => {
    const connectWS = () => {
      setWsStatus('connecting');
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus('connected');
        console.log("WebSocket connected to:", WS_URL);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          console.log("WebSocket message received:", message);

          if (message.type === 'LOCK_CONTROL') {
            const locked = message.action === 'LOCK';
            setIsLocked(locked);
            setSimServoAngle(locked ? 0 : 90);
            setSimOledText(locked ? "SYSTEM LOCKED\nREADY" : "DOOR UNLOCKED\nWELCOME");
          } else if (message.type === 'VISITOR_ALERT') {
            const newLog: AccessLog = message.log;
            setLogs(prev => [newLog, ...prev]);
            setRecentLogs(prev => [newLog, ...prev.slice(0, 9)]);
            if (newLog.decision === 'PENDING') {
              setPendingAlerts(prev => [newLog, ...prev]);
            }
          } else if (message.type === 'VISITOR_DECISION') {
            const { logId, decision } = message;
            // Update decision in state
            setLogs(prev => prev.map(l => l.id === logId ? { ...l, decision } : l));
            setRecentLogs(prev => prev.map(l => l.id === logId ? { ...l, decision } : l));
            setPendingAlerts(prev => prev.filter(l => l.id !== logId));
          } else if (message.type === 'SIMULATOR_OLED') {
            setSimOledText(message.text);
          }
        } catch (err) {
          console.error("Error parsing WS message:", err);
        }
      };

      ws.onclose = () => {
        setWsStatus('disconnected');
        console.log("WebSocket disconnected. Retrying in 5s...");
        setTimeout(connectWS, 5000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        ws.close();
      };
    };

    connectWS();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // Lock Actions
  const toggleLock = async () => {
    const action = isLocked ? 'unlock' : 'lock';
    try {
      const res = await fetch(`${API_BASE}/lock/${action}`, { method: 'POST' });
      if (res.ok) {
        setIsLocked(!isLocked);
        setSimServoAngle(isLocked ? 90 : 0);
        setSimOledText(isLocked ? "DOOR UNLOCKED\nWELCOME" : "SYSTEM LOCKED\nREADY");
      }
    } catch (err) {
      console.error(`Error sending ${action} request:`, err);
    }
  };

  // Visitor Approval Actions
  const handleVisitorDecision = async (id: number, decision: 'approve' | 'reject') => {
    try {
      const res = await fetch(`${API_BASE}/visitors/${id}/${decision}`, { method: 'POST' });
      if (res.ok) {
        setPendingAlerts(prev => prev.filter(a => a.id !== id));
        fetchData();
      }
    } catch (err) {
      console.error(`Error sending decision ${decision} for visitor ${id}:`, err);
    }
  };

  // User Actions
  const handleAddUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUserName || !newUserImage) {
      alert("Please specify a Name and select a Face Image.");
      return;
    }

    const formData = new FormData();
    formData.append('name', newUserName);
    formData.append('role', newUserRole);
    formData.append('image', newUserImage);

    try {
      const res = await fetch(`${API_BASE}/users`, {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        setNewUserName('');
        setNewUserRole('RESIDENT');
        setNewUserImage(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
        fetchData();
        alert("User added and face database reloaded!");
      } else {
        const errData = await res.json();
        alert("Error adding user: " + errData.error);
      }
    } catch (err) {
      console.error("Error adding user:", err);
    }
  };

  const handleDeleteUser = async (id: number) => {
    if (!confirm("Are you sure you want to remove this user?")) return;
    try {
      const res = await fetch(`${API_BASE}/users/${id}`, { method: 'DELETE' });
      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      console.error("Error deleting user:", err);
    }
  };

  // Simulator Actions (Simulates Hardware Events)
  const triggerSimulatedVisitor = async (type: 'authorized' | 'unauthorized') => {
    try {
      // For authorized, we will pick the first registered user's name, or default to "Vaibhav"
      const name = type === 'authorized' ? (users[0]?.name || 'Vaibhav') : 'Unknown';
      const decision = type === 'authorized' ? 'APPROVED' : 'PENDING';
      const approvedBy = type === 'authorized' ? 'AUTOMATIC' : 'PENDING';

      // Update OLED screen
      setSimOledText("VISITOR DETECTED\nPROCESSING...");
      
      // Call Spring Boot to simulate a ring
      // In simulator, we don't upload a real image, we send a request.
      // We will hit POST /api/visitors/ring using empty or mock data
      const formData = new FormData();
      formData.append('recognitionResult', String(name));
      formData.append('decision', decision);
      formData.append('approvedBy', approvedBy);
      
      const res = await fetch(`${API_BASE}/visitors/ring`, {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        console.log(`Simulated ${type} ring triggered successfully`);
        if (type === 'authorized') {
          setSimOledText(`WELCOME\n${name.toUpperCase()}`);
          setSimServoAngle(90);
          setIsLocked(false);
          // Auto relock after 5 seconds
          setTimeout(async () => {
            await fetch(`${API_BASE}/lock/lock`);
          }, 5000);
        } else {
          setSimOledText("UNKNOWN VISIT\nAWAITING DECISION");
        }
      }
    } catch (err) {
      console.error("Error triggering simulated ring:", err);
    }
  };

  // CSV Exporter
  const exportToCSV = () => {
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "ID,Timestamp,Identity,Decision,Approved By\n";
    logs.forEach(l => {
      csvContent += `${l.id},${l.timestamp},${l.recognitionResult},${l.decision},${l.approvedBy}\n`;
    });
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "doorbell_access_logs.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex h-screen bg-[#070b19] text-[#e2e8f0] overflow-hidden">
      
      {/* Sidebar */}
      <aside className="w-64 bg-[#0a0f20] border-r border-slate-800 flex flex-col justify-between p-6">
        <div>
          {/* Logo */}
          <div className="flex items-center gap-3 mb-8">
            <div className="p-2 bg-violet-600 rounded-lg glow-primary">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-lg leading-tight tracking-wide text-white">DoorAI</h1>
              <span className="text-xs text-slate-400">Access Control</span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-2">
            <button 
              onClick={() => setActiveTab('dashboard')}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${activeTab === 'dashboard' ? 'bg-violet-600/20 border border-violet-500/30 text-white' : 'text-slate-400 hover:bg-slate-800/40 hover:text-white'}`}
            >
              <Activity className="w-4 h-4" />
              Overview
            </button>
            <button 
              onClick={() => setActiveTab('logs')}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${activeTab === 'logs' ? 'bg-violet-600/20 border border-violet-500/30 text-white' : 'text-slate-400 hover:bg-slate-800/40 hover:text-white'}`}
            >
              <History className="w-4 h-4" />
              Visitor Logs
            </button>
            <button 
              onClick={() => setActiveTab('users')}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${activeTab === 'users' ? 'bg-violet-600/20 border border-violet-500/30 text-white' : 'text-slate-400 hover:bg-slate-800/40 hover:text-white'}`}
            >
              <Users className="w-4 h-4" />
              User Directory
            </button>
            <button 
              onClick={() => setActiveTab('simulator')}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all ${activeTab === 'simulator' ? 'bg-violet-600/20 border border-violet-500/30 text-white' : 'text-slate-400 hover:bg-slate-800/40 hover:text-white'}`}
            >
              <Sliders className="w-4 h-4" />
              HW Simulator
            </button>
          </nav>
        </div>

        {/* WebSocket Connection Status */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-2.5 h-2.5 rounded-full ${wsStatus === 'connected' ? 'bg-emerald-500 animate-pulse' : wsStatus === 'connecting' ? 'bg-amber-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Agent Connection
            </span>
          </div>
          <span className="text-xs text-slate-500">
            {wsStatus === 'connected' ? 'Connected to AI Engine' : wsStatus === 'connecting' ? 'Connecting to Broker...' : 'Engine Offline. Retrying...'}
          </span>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-y-auto">
        
        {/* Header */}
        <header className="h-16 border-b border-slate-800 bg-[#0a0f20]/60 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-40">
          <h2 className="text-xl font-bold tracking-tight text-white capitalize">
            {activeTab === 'users' ? 'User Directory' : activeTab === 'logs' ? 'Visitor Access Logs' : activeTab === 'simulator' ? 'Hardware Simulator Controller' : 'Dashboard Overview'}
          </h2>
          <div className="flex items-center gap-4">
            <button 
              onClick={fetchData} 
              className="p-2 text-slate-400 hover:text-white bg-slate-800/60 rounded-lg border border-slate-700 transition"
              title="Refresh Data"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <div className="text-xs font-semibold px-3 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300">
              Dev Mode ACTIVE
            </div>
          </div>
        </header>

        {/* Content Screens */}
        <div className="p-8 flex-1">
          
          {/* Pending Alerts Banner */}
          {pendingAlerts.length > 0 && (
            <div className="mb-6 animate-bounce">
              {pendingAlerts.map(alert => (
                <div key={alert.id} className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center justify-between shadow-lg glow-primary">
                  <div className="flex items-center gap-4">
                    <ShieldAlert className="w-6 h-6 text-amber-500" />
                    <div>
                      <h4 className="font-bold text-amber-200">Unknown Visitor Detected</h4>
                      <p className="text-xs text-amber-300/80">Awaiting your approval to unlock the door</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button 
                      onClick={() => handleVisitorDecision(alert.id, 'approve')}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition shadow"
                    >
                      <Check className="w-3.5 h-3.5" /> Approve Entry
                    </button>
                    <button 
                      onClick={() => handleVisitorDecision(alert.id, 'reject')}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-bold transition shadow"
                    >
                      <X className="w-3.5 h-3.5" /> Deny
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Tab 1: Dashboard Overview */}
          {activeTab === 'dashboard' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Left Column: Live camera and quick actions */}
              <div className="lg:col-span-2 space-y-6">
                
                {/* Live stream */}
                <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden">
                  <div className="p-4 bg-[#0a0f20] border-b border-slate-800 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Camera className="w-4 h-4 text-violet-500" />
                      <span className="text-sm font-bold text-slate-200">Live Camera Feed</span>
                    </div>
                    <span className="text-xs font-semibold px-2 py-0.5 bg-rose-500/20 text-rose-300 rounded-full animate-pulse border border-rose-500/30">
                      LIVE
                    </span>
                  </div>
                  <div className="aspect-video bg-slate-950 flex items-center justify-center relative">
                    {/* Img source points to Python video proxy server */}
                    <img 
                      src={`http://${hostname}:8081/video_feed`} 
                      alt="Live Stream Feed" 
                      className="w-full h-full object-cover"
                      onError={(e) => {
                        // If offline, display a beautiful placeholder
                        (e.target as HTMLImageElement).src = '';
                        (e.target as HTMLImageElement).style.display = 'none';
                        const parent = (e.target as HTMLImageElement).parentElement;
                        if (parent) {
                          const placeholder = parent.querySelector('.stream-offline-placeholder');
                          if (placeholder) placeholder.classList.remove('hidden');
                        }
                      }}
                    />
                    <div className="stream-offline-placeholder hidden flex flex-col items-center gap-2 text-slate-500 p-8 text-center">
                      <Camera className="w-12 h-12 stroke-[1.5] text-slate-600" />
                      <div>
                        <p className="text-sm font-bold text-slate-400">ESP32-CAM Stream Offline</p>
                        <p className="text-xs text-slate-600 mt-1">Start the AI Device Agent service to activate the video camera feed</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Quick Lock Control */}
                <div className="glass-panel p-6 rounded-2xl border border-slate-800 flex items-center justify-between relative overflow-hidden">
                  <div className="absolute right-0 top-0 w-32 h-full bg-gradient-to-l from-violet-600/5 to-transparent pointer-events-none" />
                  <div className="flex items-center gap-4">
                    <div className={`p-4 rounded-xl ${isLocked ? 'bg-rose-500/10 text-rose-500 border border-rose-500/20 glow-red' : 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 glow-green'}`}>
                      {isLocked ? <Lock className="w-8 h-8" /> : <Unlock className="w-8 h-8" />}
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-white">
                        Door Status: <span className={isLocked ? 'text-rose-400' : 'text-emerald-400'}>{isLocked ? 'LOCKED' : 'UNLOCKED'}</span>
                      </h3>
                      <p className="text-xs text-slate-400 mt-1">
                        {isLocked ? 'The magnetic lock is currently engaged' : 'Access granted. The magnetic lock is open'}
                      </p>
                    </div>
                  </div>
                  <button 
                    onClick={toggleLock}
                    className={`px-6 py-3 rounded-xl text-sm font-bold transition-all shadow-md ${isLocked ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-rose-600 hover:bg-rose-500 text-white'}`}
                  >
                    {isLocked ? 'Unlock Door' : 'Lock Door'}
                  </button>
                </div>
              </div>

              {/* Right Column: Status metrics and recent feed */}
              <div className="space-y-6">
                
                {/* System Metrics */}
                <div className="glass-panel p-6 rounded-2xl border border-slate-800">
                  <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-wide uppercase flex items-center gap-2">
                    <Sliders className="w-4 h-4 text-violet-500" /> System Metrics (Pi 4)
                  </h3>
                  
                  <div className="space-y-4">
                    {/* CPU */}
                    <div>
                      <div className="flex justify-between text-xs font-bold mb-1">
                        <span className="flex items-center gap-1.5 text-slate-300">
                          <Cpu className="w-3.5 h-3.5 text-slate-500" /> CPU Usage
                        </span>
                        <span>{metrics.cpuUsage}%</span>
                      </div>
                      <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                        <div 
                          className="bg-violet-500 h-full rounded-full transition-all duration-1000"
                          style={{ width: `${metrics.cpuUsage}%` }}
                        />
                      </div>
                    </div>

                    {/* RAM */}
                    <div>
                      <div className="flex justify-between text-xs font-bold mb-1">
                        <span className="flex items-center gap-1.5 text-slate-300">
                          <HardDrive className="w-3.5 h-3.5 text-slate-500" /> Memory Load
                        </span>
                        <span>{metrics.memoryUsage}%</span>
                      </div>
                      <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                        <div 
                          className="bg-indigo-500 h-full rounded-full transition-all duration-1000"
                          style={{ width: `${metrics.memoryUsage}%` }}
                        />
                      </div>
                    </div>

                    {/* Temp */}
                    <div>
                      <div className="flex justify-between text-xs font-bold mb-1">
                        <span className="flex items-center gap-1.5 text-slate-300">
                          <Thermometer className="w-3.5 h-3.5 text-slate-500" /> Temperature
                        </span>
                        <span className={metrics.temperature > 65 ? 'text-rose-400 font-bold' : 'text-slate-300'}>{metrics.temperature}°C</span>
                      </div>
                      <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                        <div 
                          className={`h-full rounded-full transition-all duration-1000 ${metrics.temperature > 60 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                          style={{ width: `${Math.min(100, (metrics.temperature / 85) * 100)}%` }}
                        />
                      </div>
                    </div>

                    {/* Meta info */}
                    <div className="border-t border-slate-800/80 pt-4 mt-2 space-y-2 text-xs">
                      <div className="flex justify-between text-slate-400">
                        <span>Pi Uptime:</span>
                        <span className="font-semibold text-slate-200 flex items-center gap-1">
                          <Clock className="w-3 h-3 text-slate-500" /> {metrics.uptime}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>Network status:</span>
                        <span className="font-semibold text-slate-200 flex items-center gap-1">
                          <Wifi className="w-3 h-3 text-slate-500" /> {metrics.network}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Recent Activity */}
                <div className="glass-panel p-6 rounded-2xl border border-slate-800 flex flex-col h-[320px]">
                  <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-wide uppercase flex items-center gap-2">
                    <History className="w-4 h-4 text-violet-500" /> Recent Activity
                  </h3>
                  <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                    {recentLogs.length === 0 ? (
                      <div className="text-center text-xs text-slate-600 py-12">
                        No activity logged yet.
                      </div>
                    ) : (
                      recentLogs.map((log) => (
                        <div key={log.id} className="p-3 bg-slate-900/40 border border-slate-800/50 rounded-xl flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <div className={`p-1.5 rounded-lg ${log.decision === 'APPROVED' ? 'bg-emerald-500/10 text-emerald-500' : log.decision === 'REJECTED' ? 'bg-rose-500/10 text-rose-500' : 'bg-amber-500/10 text-amber-500'}`}>
                              {log.decision === 'APPROVED' ? <UserCheck className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
                            </div>
                            <div>
                              <p className="text-xs font-bold text-white leading-tight">
                                {log.recognitionResult}
                              </p>
                              <span className="text-[10px] text-slate-500">
                                {new Date(String(log.timestamp)).toLocaleTimeString()}
                              </span>
                            </div>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${log.decision === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-300' : log.decision === 'REJECTED' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}`}>
                            {log.decision}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>

              </div>

            </div>
          )}

          {/* Tab 2: Visitor Logs */}
          {activeTab === 'logs' && (
            <div className="glass-panel rounded-2xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="font-bold text-lg text-white">All Activity Events</h3>
                  <p className="text-xs text-slate-400">Total doorbell and face access history logs</p>
                </div>
                <button 
                  onClick={exportToCSV}
                  className="flex items-center gap-1.5 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-sm font-semibold border border-slate-700 transition"
                >
                  <Download className="w-4 h-4" /> Export CSV
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm text-slate-300">
                  <thead className="bg-[#0a0f20]/80 border-b border-slate-800 text-slate-400 text-xs font-bold uppercase tracking-wider">
                    <tr>
                      <th className="px-6 py-4">Snapshot</th>
                      <th className="px-6 py-4">Time</th>
                      <th className="px-6 py-4">Identity</th>
                      <th className="px-6 py-4">Decision</th>
                      <th className="px-6 py-4">Approved By</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/80">
                    {logs.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="text-center py-12 text-slate-500">
                          No access logs recorded in database.
                        </td>
                      </tr>
                    ) : (
                      logs.map((log) => (
                        <tr key={log.id} className="hover:bg-slate-900/20 transition-all">
                          <td className="px-6 py-3">
                            <div className="w-12 h-12 bg-slate-950 rounded-lg overflow-hidden border border-slate-800 flex items-center justify-center">
                              {log.imagePath ? (
                                <img 
                                  src={`${STATIC_BASE}/visitor_snapshots/${log.imagePath}`} 
                                  alt="Visitor" 
                                  className="w-full h-full object-cover"
                                  onError={(e) => {
                                    (e.target as HTMLImageElement).src = 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=100&h=100&q=80'; // Fallback sample
                                  }}
                                />
                              ) : (
                                <Camera className="w-5 h-5 text-slate-600" />
                              )}
                            </div>
                          </td>
                          <td className="px-6 py-4 font-medium text-slate-400">
                            {new Date(String(log.timestamp)).toLocaleString()}
                          </td>
                          <td className="px-6 py-4 font-bold text-white">
                            {log.recognitionResult}
                          </td>
                          <td className="px-6 py-4">
                            <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${log.decision === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-300' : log.decision === 'REJECTED' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}`}>
                              {log.decision}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-xs font-semibold text-slate-400 uppercase tracking-wide">
                            {log.approvedBy || '-'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tab 3: User Directory */}
          {activeTab === 'users' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Left Form: Add authorized user */}
              <div className="glass-panel p-6 rounded-2xl border border-slate-800 h-fit">
                <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                  <Plus className="w-5 h-5 text-violet-500" /> Add Authorized User
                </h3>
                <form onSubmit={handleAddUser} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-400 mb-1 tracking-wide uppercase">Full Name</label>
                    <input 
                      type="text" 
                      value={newUserName}
                      onChange={(e) => setNewUserName(e.target.value)}
                      placeholder="e.g. John Doe"
                      className="w-full bg-[#070b19] border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-400 mb-1 tracking-wide uppercase">Role / Classification</label>
                    <select
                      value={newUserRole}
                      onChange={(e) => setNewUserRole(e.target.value)}
                      className="w-full bg-[#070b19] border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-violet-500 transition"
                    >
                      <option value="RESIDENT">Resident</option>
                      <option value="ADMIN">Administrator</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-400 mb-1 tracking-wide uppercase">Face Photo Profile</label>
                    <input 
                      type="file" 
                      accept="image/*"
                      ref={fileInputRef}
                      onChange={(e) => {
                        if (e.target.files && e.target.files[0]) {
                          setNewUserImage(e.target.files[0]);
                        }
                      }}
                      className="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-violet-600/20 file:text-violet-300 hover:file:bg-violet-600/30 file:cursor-pointer cursor-pointer border border-slate-800 rounded-lg p-2 bg-[#070b19] focus:outline-none"
                    />
                  </div>

                  <button 
                    type="submit"
                    className="w-full py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm font-bold transition shadow-md glow-primary"
                  >
                    Register User Face
                  </button>
                </form>
              </div>

              {/* Right Directory: Authorized users list */}
              <div className="lg:col-span-2 glass-panel p-6 rounded-2xl border border-slate-800">
                <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                  <Users className="w-5 h-5 text-violet-500" /> Authorized Residents Directory
                </h3>
                
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-slate-300">
                    <thead className="bg-[#0a0f20]/80 border-b border-slate-800 text-slate-400 text-xs font-bold uppercase">
                      <tr>
                        <th className="px-6 py-3">Profile Face</th>
                        <th className="px-6 py-3">Name</th>
                        <th className="px-6 py-3">Classification</th>
                        <th className="px-6 py-3">Registered At</th>
                        <th className="px-6 py-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {users.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="text-center py-12 text-slate-500">
                            No users registered. Use the panel on the left to add a user.
                          </td>
                        </tr>
                      ) : (
                        users.map((user) => (
                          <tr key={user.id} className="hover:bg-slate-900/10 transition-all">
                            <td className="px-6 py-3">
                              <div className="w-10 h-10 bg-slate-950 rounded-full overflow-hidden border border-slate-800 flex items-center justify-center">
                                <img 
                                  src={`${STATIC_BASE}/stored_faces/${user.imagePath}`} 
                                  alt={String(user.name)} 
                                  className="w-full h-full object-cover"
                                  onError={(e) => {
                                    (e.target as HTMLImageElement).src = 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=100&h=100&q=80'; // Fallback
                                  }}
                                />
                              </div>
                            </td>
                            <td className="px-6 py-3 font-bold text-white">{user.name}</td>
                            <td className="px-6 py-3">
                              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-violet-900/30 text-violet-300 border border-violet-800/40">
                                {user.role}
                              </span>
                            </td>
                            <td className="px-6 py-3 text-xs text-slate-400">
                              {new Date(String(user.createdAt)).toLocaleDateString()}
                            </td>
                            <td className="px-6 py-3">
                              <button 
                                onClick={() => handleDeleteUser(user.id)}
                                className="p-1.5 text-rose-400 hover:text-white hover:bg-rose-600/30 rounded-lg transition"
                                title="Remove User"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

            </div>
          )}

          {/* Tab 4: Hardware Simulator */}
          {activeTab === 'simulator' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              
              {/* Simulator Controller Panel */}
              <div className="glass-panel p-8 rounded-2xl border border-slate-800 flex flex-col justify-between">
                <div>
                  <h3 className="font-bold text-lg text-white mb-2 flex items-center gap-2">
                    <Sliders className="w-5 h-5 text-violet-500" /> Simulated Hardware Commands
                  </h3>
                  <p className="text-xs text-slate-400 mb-6 leading-relaxed">
                    Test the system's response loops without real physical microcontrollers or sensors. You can trigger simulated rings to test auto-unlocks and notifications.
                  </p>

                  <div className="space-y-4">
                    <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-xl">
                      <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wide mb-2">Visitor IR Range Detector</h4>
                      <div className="flex gap-3">
                        <button 
                          onClick={() => triggerSimulatedVisitor('authorized')}
                          className="flex-1 py-3 bg-emerald-600/20 hover:bg-emerald-600 text-emerald-300 hover:text-white border border-emerald-500/30 rounded-xl text-sm font-bold transition duration-200"
                        >
                          Trigger Resident (Auto-Unlock)
                        </button>
                        <button 
                          onClick={() => triggerSimulatedVisitor('unauthorized')}
                          className="flex-1 py-3 bg-amber-600/20 hover:bg-amber-600 text-amber-300 hover:text-white border border-amber-500/30 rounded-xl text-sm font-bold transition duration-200"
                        >
                          Trigger Stranger (Approval Loop)
                        </button>
                      </div>
                    </div>

                    <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-xl flex items-center justify-between">
                      <div>
                        <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wide">Manual Tamper Trigger</h4>
                        <p className="text-[10px] text-slate-500 mt-0.5">Simulates force-prying open the device frame</p>
                      </div>
                      <button 
                        onClick={() => {
                          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                            wsRef.current.send(JSON.stringify({
                              type: "TAMPER_ALERT",
                              timestamp: new Date().toISOString()
                            }));
                            alert("Simulated Tamper Alert Broadcasted!");
                          } else {
                            alert("WebSocket offline. Cannot trigger.");
                          }
                        }}
                        className="px-4 py-2 bg-rose-600/20 hover:bg-rose-600 text-rose-300 hover:text-white border border-rose-500/30 rounded-lg text-xs font-bold transition"
                      >
                        Trigger Alarm
                      </button>
                    </div>
                  </div>
                </div>

                <div className="border-t border-slate-800/80 pt-6 mt-8 text-xs text-slate-500">
                  <span className="font-bold text-slate-400">GPIO Pin Out logs:</span>
                  <ul className="list-disc pl-4 space-y-1 mt-2 text-[10px] text-slate-500">
                    <li>OLED: SDA = GPIO2 (Pin 3), SCL = GPIO3 (Pin 5)</li>
                    <li>IR Sensor: Digital IN = GPIO17 (Pin 11)</li>
                    <li>Servo: PWM Signal = GPIO18 (Pin 12)</li>
                  </ul>
                </div>
              </div>

              {/* Physical Output Representation */}
              <div className="space-y-6">
                
                {/* Simulated SSD1306 OLED Screen */}
                <div className="glass-panel p-6 rounded-2xl border border-slate-800">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-pulse" /> Local OLED Display (SSD1306 128x64)
                  </h4>
                  <div className="w-full aspect-[2/1] bg-[#0c182b] border-[8px] border-slate-800 rounded-xl flex items-center justify-center p-4 relative overflow-hidden shadow-inner font-mono text-cyan-400">
                    {/* OLED Screen lines */}
                    <div className="text-center select-none font-bold text-sm tracking-widest whitespace-pre-line">
                      {simOledText}
                    </div>
                    {/* Blue horizontal banding filter */}
                    <div className="absolute inset-0 bg-gradient-to-b from-cyan-400/5 via-transparent to-cyan-400/5 pointer-events-none" />
                  </div>
                </div>

                {/* Simulated SG90 Servo motor position */}
                <div className="glass-panel p-6 rounded-2xl border border-slate-800">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4">
                    Physical SG90 Servo Actuator (PWM Pin 12)
                  </h4>
                  <div className="flex items-center justify-between p-4 bg-slate-900/60 border border-slate-800 rounded-xl">
                    <div className="flex flex-col gap-1">
                      <span className="text-xs font-bold text-slate-300">Angle Degree</span>
                      <span className="text-2xl font-bold text-white font-mono">{simServoAngle}°</span>
                      <span className="text-[10px] text-slate-500 font-semibold tracking-wider uppercase">
                        {simServoAngle === 0 ? 'LOCKED (DEADBOLT ENGAGED)' : 'UNLOCKED (ACCESS PASS)'}
                      </span>
                    </div>

                    {/* Dial Gauge Representation */}
                    <div className="w-24 h-24 relative flex items-center justify-center">
                      <svg className="w-full h-full transform -rotate-90">
                        <circle 
                          cx="48" cy="48" r="38" 
                          stroke="rgba(255, 255, 255, 0.05)" 
                          strokeWidth="8" 
                          fill="transparent" 
                        />
                        <circle 
                          cx="48" cy="48" r="38" 
                          stroke={simServoAngle === 0 ? "rgba(239, 68, 68, 0.6)" : "rgba(16, 185, 129, 0.6)"} 
                          strokeWidth="8" 
                          fill="transparent" 
                          strokeDasharray={2 * Math.PI * 38}
                          strokeDashoffset={2 * Math.PI * 38 * (1 - simServoAngle / 180)}
                          className="transition-all duration-500 ease-out"
                        />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center font-bold text-xs text-slate-400">
                        {simServoAngle === 0 ? '0°' : '90°'}
                      </div>
                    </div>
                  </div>
                </div>

              </div>

            </div>
          )}

        </div>
      </main>
    </div>
  );
}
