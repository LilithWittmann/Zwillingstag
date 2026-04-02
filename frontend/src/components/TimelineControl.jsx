import React from 'react'

export default function TimelineControl({
  speeches,
  currentSpeechId,
  onSelect,
}) {
  if (!speeches || speeches.length === 0) return null

  return (
    <div className="timeline-control">
      <div className="timeline-label">Redebeiträge</div>
      <div className="timeline-list">
        {speeches.map((speech) => {
          const isActive = speech.id === currentSpeechId
          return (
            <button
              key={speech.id}
              className={`timeline-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelect(speech.id)}
              title={speech.text?.slice(0, 120)}
            >
              <span className="timeline-speaker">{speech.speaker_name}</span>
              {speech.speaker_party && (
                <span className="timeline-party">{speech.speaker_party}</span>
              )}
              <span className="timeline-topic">
                {speech.topic || speech.session_title || ''}
              </span>
              <span className="timeline-date">{formatShortDate(speech.date)}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function formatShortDate(dateStr) {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
    })
  } catch {
    return dateStr
  }
}
