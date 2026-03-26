import { useEffect, useMemo, useState } from 'react';
import apiClient from '../api/client';
import EventLogFeed from '../components/EventLogFeed';
import MtdStatusBadge from '../components/MtdStatusBadge';
import { useAuth } from '../context/AuthContext';

export default function ChallengePage() {
  const { user } = useAuth();
  const [challenge, setChallenge] = useState(null);
  const [scenarios, setScenarios] = useState([]); // 🚨 เก็บข้อมูลโจทย์ใน Catalog
  const [statusLoading, setStatusLoading] = useState(true);
  const [eventType, setEventType] = useState('attack_detected');
  const [error, setError] = useState('');

  const activeAttack = useMemo(() => eventType === 'attack_detected', [eventType]);

  const loadData = async () => {
    setStatusLoading(true);
    setError('');
    try {
      // 1. เช็คก่อนว่ามีโจทย์ที่กำลังรันอยู่ไหม?
      const { data: statusData } = await apiClient.get('/api/challenge/status');
      const own = Array.isArray(statusData) ? statusData.find((row) => row.team_id === user?.id && row.status === 'active') : null;
      setChallenge(own || null);

      // 2. ถ้าไม่มีโจทย์รันอยู่ ให้ไปดึง Catalog โจทย์ทั้งหมดมาโชว์หน้า Lobby
      if (!own) {
        const { data: scenarioData } = await apiClient.get('/api/scenario/list');
        setScenarios(scenarioData || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    if (!user) return;
    loadData();
  }, [user]);

  // 🚨 ฟังก์ชันใหม่: เวลานักเรียนกดเลือกโจทย์จาก Catalog
  const startChallenge = async (scenarioId) => {
    try {
      setError('');
      setStatusLoading(true);
      await apiClient.post('/api/challenge/start', { scenario_id: scenarioId });
      await loadData(); // โหลดข้อมูลใหม่ หน้าเว็บจะสลับไปโหมด Console ทันที!
    } catch (err) {
      setError(err.message);
      setStatusLoading(false);
    }
  };

  const triggerMtd = async () => {
    if (!challenge?.id) return;
    try {
      const { data } = await apiClient.post('/api/challenge/trigger-mtd', {
        challenge_id: challenge.id,
        event_type: eventType
      });
      if (data.new_port) {
        setChallenge((prev) => ({ ...prev, port: data.new_port, current_port: data.new_port }));
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const stopChallenge = async () => {
    if (!challenge?.id) return;
    try {
      await apiClient.post('/api/challenge/stop', { challenge_id: challenge.id });
      await loadData(); // 🚨 โหลดข้อมูลใหม่ หน้าเว็บจะเด้งกลับไปหน้า Lobby!
    } catch (err) {
      setError(err.message);
    }
  };

  const resetChallenge = async () => {
    if (!challenge?.id) return;
    try {
      const { data } = await apiClient.post('/api/challenge/reset', { challenge_id: challenge.id });
      setChallenge((prev) => ({ ...prev, ...data }));
      await loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  // 🚨 แยกหมวดหมู่โจทย์ (Web, Crypto, etc.)
  const groupedScenarios = scenarios.reduce((acc, curr) => {
    const type = curr.type || 'other';
    if (!acc[type]) acc[type] = [];
    acc[type].push(curr);
    return acc;
  }, {});

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn">
      {/* --- HEADER --- */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-3xl font-bold text-green-400">
          {challenge ? 'Challenge Console' : 'Challenge Catalog'}
        </h1>
        {challenge && (
          <MtdStatusBadge
            status={challenge.status || 'stopped'}
            currentPort={challenge.current_port || challenge.port}
            activeAttack={activeAttack}
          />
        )}
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}
      {statusLoading && <p className="text-sm text-slate-300">Loading modules...</p>}

      {/* --- LOBBY VIEW: หน้ารวมโจทย์แบ่งหมวดหมู่ (จะโชว์ก็ต่อเมื่อยังไม่ได้เล่นโจทย์ไหน) --- */}
      {!statusLoading && !challenge ? (
        <div className="space-y-8">
          {Object.keys(groupedScenarios).length === 0 ? (
            <div className="terminal-panel rounded-lg p-4 text-sm text-slate-400">
              No challenges available in the catalog. Ask your instructor to create some.
            </div>
          ) : (
            Object.entries(groupedScenarios).map(([type, list]) => (
              <div key={type} className="terminal-panel rounded-lg p-6">
                <h2 className="mb-4 text-xl font-bold uppercase tracking-wider text-green-500 border-b border-green-500/20 pb-2">
                  {type.replace('_', ' ')} Challenges
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {list.map((s) => (
                    <div key={s.id} className="flex flex-col justify-between rounded-md border border-slate-700 bg-slate-800/50 p-4 transition hover:border-green-500/50">
                      <div>
                        <h3 className="text-lg font-semibold text-white">{s.name}</h3>
                        <p className="mt-1 text-sm text-slate-400">Difficulty: <span className="text-amber-400 uppercase">{s.difficulty}</span></p>
                      </div>
                      <button
                        onClick={() => startChallenge(s.id)}
                        className="mt-4 w-full rounded bg-green-600/20 py-2 text-sm font-semibold text-green-400 hover:bg-green-600 hover:text-white transition"
                      >
                        Start Instance
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      ) : null}

      {/* --- CONSOLE VIEW: หน้าจอเจาะระบบ (จะโชว์ก็ต่อเมื่อกด Start Instance แล้ว) --- */}
      {!statusLoading && challenge ? (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <div className="terminal-panel rounded-lg p-4">
            <h2 className="font-display text-lg font-semibold text-green-400">MTD Controls</h2>
            <p className="mt-2 text-xs text-slate-300">
              Active target port: <span className="font-mono text-amber-400">{challenge.current_port || challenge.port}</span>
            </p>

            <select
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
              className="mt-4 w-full rounded-md border border-green-500/30 bg-gray-900/50 px-3 py-2 text-sm text-green-300"
            >
              <option value="attack_detected">attack_detected</option>
              <option value="honeypot_hit">honeypot_hit</option>
              <option value="system_log">system_log</option>
            </select>

            <div className="mt-4 grid gap-2">
              <button type="button" onClick={triggerMtd} className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-500">
                Trigger Adaptive MTD
              </button>
              <button type="button" onClick={resetChallenge} className="rounded-md border border-amber-500/40 px-4 py-2 text-sm text-amber-300">
                Reset Session
              </button>
              <button type="button" onClick={stopChallenge} className="rounded-md border border-red-500/50 px-4 py-2 text-sm text-red-300">
                Terminate Instance
              </button>
            </div>
          </div>

          <EventLogFeed challengeId={challenge.id} />
        </div>
      ) : null}
    </div>
  );
}