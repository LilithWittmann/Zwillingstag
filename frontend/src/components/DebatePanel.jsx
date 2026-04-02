import React from 'react'

const PARTY_BADGE_COLORS = {
  SPD: '#c0392b',
  CDU: '#1a1a2e',
  CSU: '#16213e',
  GRÜNE: '#27ae60',
  FDP: '#f1c40f',
  AfD: '#2980b9',
  LINKE: '#8e44ad',
}

export default function DebatePanel({ speech, isLive }) {
  if (!speech) {
    return (
      <div className="debate-panel debate-panel--empty">
        <div className="debate-empty-icon">🏛️</div>
        <p>Lade Plenardebatte…</p>
      </div>
    )
  }

  const partyColor = PARTY_BADGE_COLORS[speech.speaker_party] || '#555'

  return (
    <div className="debate-panel">
      <div className="debate-header">
        <div className="debate-meta">
          {isLive && (
            <span className="live-badge">
              <span className="live-dot" /> LIVE
            </span>
          )}
          <span className="debate-date">{formatDate(speech.date)}</span>
          {speech.session_title && (
            <span className="debate-session">{speech.session_title}</span>
          )}
        </div>
        {speech.topic && (
          <div className="debate-topic">Tagesordnungspunkt: {speech.topic}</div>
        )}
      </div>

      <div className="debate-speaker">
        <div
          className="speaker-party-badge"
          style={{ background: partyColor }}
        >
          {speech.speaker_party || '—'}
        </div>
        <div className="speaker-name">{speech.speaker_name}</div>
      </div>

      <div className="debate-text">
        <p>{speech.text}</p>
      </div>
    </div>
  )
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: 'long',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}
