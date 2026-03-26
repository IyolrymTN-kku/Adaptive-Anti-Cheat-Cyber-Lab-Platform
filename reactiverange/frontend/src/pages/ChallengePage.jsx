import { useEffect, useMemo, useState } from 'react';
import apiClient from '../api/client';
import EventLogFeed from '../components/EventLogFeed';
import MtdStatusBadge from '../components/MtdStatusBadge';
import { useAuth } from '../context/AuthContext';

export default function ChallengePage() {
  const { user } = useAuth();
  const [challenge, setChallenge] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [solvedIds, setSolvedIds] = useState([]);
  const [statusLoading, setStatusLoading] = useState(true);
  const [error, setError] = useState('');
  
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [flagInput, setFlagInput] = useState('');
  const [submitStatus, setSubmitStatus] = useState(null);

  const loadData = async () => {
    setStatusLoading(true);
    setError('');
    try {
      const { data: statusData } = await apiClient.get('/api/challenge/status');
      
      if (Array.isArray(statusData)) {
        // หาข้อที่กำลัง Active อยู่
        const own = statusData.find((row) => row.team_id === user?.id && row.status === 'active');
        setChallenge(own || null);

        const solved = statusData
          .filter(row => row.status === 'solved' && row.team_id === user?.id)
          .map(row => row.scenario_id);
        setSolvedIds(solved);
      } else {
        setChallenge(null);
        setSolvedIds([]);
      }

      const { data: scenarioData } = await apiClient.get('/api/scenario/list');
      setScenarios(scenarioData || []);
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

  const openModal = (scenario) => {
    setSelectedScenario(scenario);
    setSubmitStatus(null);
    setFlagInput('');
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setSelectedScenario(null);
    setSubmitStatus(null);
    loadData(); // อัปเดตข้อมูลเผื่อเพิ่งแก้โจทย์เสร็จ
  };

  const startChallenge = async (scenarioId) => {
    try {
      setError('');
      await apiClient.post('/api/challenge/start', { scenario_id: scenarioId });
      await loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const stopChallenge = async () => {
    if (!challenge?.id) return;
    try {
      await apiClient.post('/api/challenge/stop', { challenge_id: challenge.id });
      await loadData();
      closeModal(); 
    } catch (err) {
      setError(err.message);
    }
  };

  const submitFlag = async () => {
    if (!flagInput.trim()) return;
    setSubmitStatus(null);
    try {
      const { data } = await apiClient.post('/api/challenge/submit', {
        challenge_id: challenge.id,
        flag: flagInput
      });
      if (data.success) {
        setSubmitStatus({ type: 'success', msg: data.message });
        setTimeout(() => {
          loadData();
        }, 2000);
      } else {
        setSubmitStatus({ type: 'error', msg: data.message });
      }
    } catch (err) {
      setSubmitStatus({ type: 'error', msg: err.message || "Submission failed" });
    }
  };

  const isCurrentActive = challenge && selectedScenario && challenge.scenario_id === selectedScenario.id;

  return (
    <div className="mx-auto mt-8 w-full max-w-7xl px-4 animate-fadeIn pb-12">
      <div className="mb-8 flex flex-wrap items-center justify-between border-b border-gray-200 dark:border-slate-700 pb-4">
        <div>
          <h1 className="font-display text-3xl font-bold text-gray-900 dark:text-white">picoGym <span className="text-green-500">Reactive Range</span></h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">Practice your skills in an adaptive, reactive environment.</p>
        </div>
        {challenge && (
          <div className="flex items-center gap-3 bg-white dark:bg-slate-800 px-4 py-2 rounded-lg border border-gray-200 dark:border-green-500/30 shadow-sm">
            <span className="text-sm font-semibold text-gray-700 dark:text-slate-300">Active Instance:</span>
            <MtdStatusBadge
              status={challenge.status || 'stopped'}
              currentPort={challenge.current_port || challenge.port}
              activeAttack={false}
            />
          </div>
        )}
      </div>

      {statusLoading && <p className="text-sm text-gray-500 dark:text-slate-300">Loading modules...</p>}

      {!statusLoading && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {scenarios.map((s) => {
            const isThisActive = challenge?.scenario_id === s.id;
            const isSolved = solvedIds.includes(s.id); // 🚨 เช็คว่าแก้ข้อนี้หรือยัง

            return (
              <div 
                key={s.id} 
                onClick={() => openModal(s)}
                className={`relative flex flex-col justify-between rounded-xl border p-5 cursor-pointer transition-all duration-200 hover:-translate-y-1 hover:shadow-lg ${
                  isThisActive ? 'border-green-500 bg-green-50 dark:bg-slate-800 shadow-green-900/20' : 
                  isSolved ? 'border-blue-500/50 bg-blue-50/50 dark:bg-blue-900/10' :
                  'border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800/60 hover:border-gray-300 dark:hover:border-slate-500 shadow-sm'
                }`}
              >
                {isThisActive && (
                  <span className="absolute -top-3 -right-3 flex h-6 w-6 items-center justify-center rounded-full bg-green-500 text-xs font-bold text-white shadow-lg">
                    <div className="h-2 w-2 rounded-full bg-white animate-pulse"></div>
                  </span>
                )}
                {isSolved && !isThisActive && (
                  <span className="absolute -top-3 -right-3 flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>
                  </span>
                )}

                <div className={isSolved ? 'opacity-70' : ''}>
                  <div className="flex flex-wrap gap-2 mb-3">
                    <span className="rounded bg-gray-200 dark:bg-slate-700 px-2 py-1 text-[10px] font-bold uppercase text-gray-700 dark:text-white tracking-wider">
                      {s.type.replace('_', ' ')}
                    </span>
                    <span className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${
                      s.difficulty === 'easy' ? 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400' :
                      s.difficulty === 'medium' ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400' :
                      'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400'
                    }`}>
                      {s.difficulty}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2">{s.name}</h3>
                  <p className="text-xs text-gray-500 dark:text-slate-400 line-clamp-2">{s.description || 'No description provided.'}</p>
                </div>
                
                <div className={`mt-4 border-t border-gray-100 dark:border-slate-700 pt-3 flex items-center justify-between text-xs font-semibold ${isSolved ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-slate-400'}`}>
                  <span>{isSolved ? 'SOLVED' : 'Autor: AI-Generated'}</span>
                  <span>{s.created_at ? new Date(s.created_at).toLocaleDateString() : 'N/A'}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* MODAL */}
      {isModalOpen && selectedScenario && (() => {
        const isSolved = solvedIds.includes(selectedScenario.id);

        return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl">
            
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 px-6 py-4 backdrop-blur">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
                {selectedScenario.name}
                {isCurrentActive && <span className="text-sm font-normal px-2 py-0.5 bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400 rounded border border-green-200 dark:border-green-500/30">RUNNING</span>}
                {isSolved && !isCurrentActive && <span className="text-sm font-bold px-2 py-0.5 bg-blue-100 text-blue-700 dark:bg-blue-600 dark:text-white rounded border border-blue-200 dark:border-blue-500">SOLVED ✅</span>}
              </h2>
              <button onClick={closeModal} className="text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-white transition text-xl p-1">✕</button>
            </div>

            <div className="p-6">
              <div className="grid gap-8 lg:grid-cols-[1fr_300px]">
                
                <div>
                  <h3 className="text-sm font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider mb-2">Description</h3>
                  <div className="prose prose-slate dark:prose-invert max-w-none text-sm text-gray-700 dark:text-slate-300 mb-6 bg-gray-50 dark:bg-slate-800/50 p-4 rounded-lg border border-gray-100 dark:border-slate-700/50">
                    <p>{selectedScenario.description}</p>
                  </div>

                  {isSolved && !isCurrentActive ? (
                    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-500/30 rounded-lg p-8 text-center animate-fadeIn">
                      <div className="text-5xl mb-4">🏆</div>
                      <h3 className="text-2xl font-bold text-blue-700 dark:text-blue-400 mb-2">Challenge Solved!</h3>
                      <p className="text-gray-600 dark:text-slate-300 mb-6">You have successfully captured the flag and earned your points.</p>
                      <button 
                        onClick={closeModal}
                        className="px-8 py-2 rounded-lg font-bold text-white bg-blue-600 hover:bg-blue-500 shadow-lg transition-all"
                      >
                        Back to Challenges
                      </button> 
                    </div>
                  ) : !isCurrentActive ? (
                    <div className="bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700 rounded-lg p-6 text-center">
                      <p className="text-sm text-gray-600 dark:text-slate-400 mb-4">This challenge launches an instance on demand.<br/>Its current status is: <span className="text-blue-500 dark:text-blue-400 font-mono">NOT_RUNNING</span></p>
                      <button 
                        onClick={() => startChallenge(selectedScenario.id)}
                        disabled={challenge !== null}
                        className={`px-8 py-3 rounded-lg font-bold text-white shadow-lg transition-all ${
                          challenge !== null 
                          ? 'bg-gray-400 dark:bg-slate-600 cursor-not-allowed opacity-50' 
                          : 'bg-blue-600 hover:bg-blue-500 hover:shadow-blue-500/25 active:scale-95'
                        }`}
                      >
                        {challenge !== null ? 'Another Instance is Running' : 'Launch Instance'}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-6 animate-fadeIn">
                      <div className="bg-green-50 dark:bg-green-900/10 border border-green-200 dark:border-green-500/30 rounded-lg p-5">
                        <p className="text-sm text-gray-700 dark:text-slate-300 mb-3">
                          The target system is running here: <a href={`http://localhost:${challenge.current_port || challenge.port}`} target="_blank" rel="noreferrer" className="text-green-600 dark:text-green-400 font-mono hover:underline font-bold text-lg block mt-1">http://localhost:{challenge.current_port || challenge.port}</a>
                        </p>
                        <p className="text-xs text-amber-600 dark:text-amber-400/80 mb-4 flex items-center gap-2">
                          <span className="inline-block w-2 h-2 rounded-full bg-amber-500 dark:bg-amber-400 animate-pulse"></span>
                          Instance will auto-terminate after 15 minutes of inactivity.
                        </p>
                        <div className="pt-2">
                            <button onClick={stopChallenge} className="text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 text-sm font-semibold transition underline">
                              Terminate Instance
                            </button>
                        </div>
                      </div>
                      {error && <p className="text-sm text-red-500 dark:text-red-400">{error}</p>}
                    </div>
                  )}

                  {isCurrentActive && (
                    <div className="mt-8">
                        <div className="flex gap-3">
                          <input 
                            type="text" 
                            value={flagInput}
                            onChange={(e) => setFlagInput(e.target.value)}
                            placeholder="FLAG{...}" 
                            className="flex-1 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-4 py-2 text-gray-900 dark:text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                          />
                          <button 
                            onClick={submitFlag}
                            className="rounded-lg bg-blue-600 px-6 py-2 font-bold text-white hover:bg-blue-500 transition"
                          >
                            Submit Flag
                          </button>
                        </div>
                        {submitStatus && (
                          <div className={`mt-3 p-3 rounded-md text-sm font-medium animate-fadeIn ${
                            submitStatus.type === 'success' 
                            ? 'bg-green-100 text-green-800 dark:bg-green-500/20 dark:text-green-400 border border-green-200 dark:border-green-500/30' 
                            : 'bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-400 border border-red-200 dark:border-red-500/30'
                          }`}>
                            {submitStatus.type === 'success' ? '🎉 ' : '❌ '}
                            {submitStatus.msg}
                          </div>
                        )}
                    </div>
                  )}
                </div>

                <div className="hidden lg:block border-l border-gray-200 dark:border-slate-700 pl-8">
                  {isCurrentActive ? (
                    <div className="h-full">
                      <EventLogFeed challengeId={challenge.id} />
                    </div>
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-center opacity-50">
                      <svg className="w-12 h-12 text-gray-400 dark:text-slate-500 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                      <p className="text-sm text-gray-500 dark:text-slate-400">Launch the instance to view the Live Event Log.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
        );
      })()}
    </div>
  );
}