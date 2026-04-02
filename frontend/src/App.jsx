import React, { useEffect, useState } from 'react'
import { useSimulation } from './hooks/useSimulation'
import ParliamentView from './components/ParliamentView'
import DebatePanel from './components/DebatePanel'
import TimelineControl from './components/TimelineControl'
import ReactionLegend from './components/ReactionLegend'

export default function App() {
  const { state, connected, selectSpeech, refresh } = useSimulation()
  const [members, setMembers] = useState([])

  // Load members once
  useEffect(() => {
    fetch('/api/members')
      .then((r) => r.json())
      .then(setMembers)
      .catch(console.error)
  }, [])

  const currentSpeech = state?.current_speech ?? null
  const reactions = state?.reactions ?? []
  const speeches = state?.available_speeches ?? []
  const isLive = state?.is_live ?? false

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <span className="header-icon">🏛️</span>
          <div>
            <h1 className="header-title">Zwillingstag</h1>
            <p className="header-subtitle">CDU/CSU Digital Twin · Bundestag</p>
          </div>
        </div>
        <div className="header-status">
          <span className={`connection-dot ${connected ? 'connected' : 'disconnected'}`} />
          <span className="connection-label">
            {connected ? 'Verbunden' : 'Verbindung wird hergestellt…'}
          </span>
          <button className="refresh-btn" onClick={refresh} title="Aktualisieren">
            ↺
          </button>
        </div>
      </header>

      {/* Main layout */}
      <main className="app-main">
        {/* Left sidebar: debate + timeline */}
        <aside className="sidebar-left">
          <DebatePanel speech={currentSpeech} isLive={isLive} />
          <TimelineControl
            speeches={speeches}
            currentSpeechId={currentSpeech?.id}
            onSelect={selectSpeech}
          />
        </aside>

        {/* Center: parliament view */}
        <section className="parliament-section">
          {members.length > 0 ? (
            <ParliamentView members={members} reactions={reactions} />
          ) : (
            <div className="loading-spinner">
              <div className="spinner" />
              <p>Lade Abgeordnete…</p>
            </div>
          )}
          <ReactionLegend />
        </section>
      </main>
    </div>
  )
}
