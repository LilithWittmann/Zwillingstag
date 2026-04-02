import React, { useState } from 'react'

const PARTY_COLORS = {
  CDU: '#1a1a2e',
  CSU: '#16213e',
}

const REACTION_ICONS = {
  clap: '👏',
  remark: '💬',
  question: '❓',
  silent: null,
}

export default function MemberSeat({ member, reaction, style }) {
  const [hovered, setHovered] = useState(false)
  const [photoError, setPhotoError] = useState(false)
  const reactionType = reaction?.reaction_type || 'silent'
  const intensity = reaction?.intensity || 1
  const text = reaction?.text

  const initials = member.name
    .split(' ')
    .map((w) => w[0])
    .filter(Boolean)
    .join('')
    .slice(0, 2)
    .toUpperCase()

  const partyColor = PARTY_COLORS[member.party] || '#1a1a2e'
  const isActive = reactionType !== 'silent'
  const showPhoto = member.photo_url && !photoError

  return (
    <div
      className={`member-seat ${reactionType} ${isActive ? 'active' : ''}`}
      style={{
        ...style,
        '--intensity': intensity,
        '--party-color': partyColor,
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label={`${member.name}: ${reactionType}${text ? ` – ${text}` : ''}`}
    >
      {/* Avatar */}
      <div className={`seat-avatar ${showPhoto ? 'has-photo' : ''}`}>
        {showPhoto ? (
          <img
            src={member.photo_url}
            alt={member.name}
            className="seat-photo"
            onError={() => setPhotoError(true)}
            loading="lazy"
          />
        ) : (
          <span className="seat-initials">{initials}</span>
        )}
        {reactionType === 'clap' && (
          <div
            className="clap-animation"
            style={{ '--clap-count': intensity }}
          >
            <span>👏</span>
          </div>
        )}
      </div>

      {/* Reaction bubble */}
      {(reactionType === 'remark' || reactionType === 'question') && text && (
        <div className={`speech-bubble bubble-${reactionType}`}>
          <span className="bubble-icon">
            {REACTION_ICONS[reactionType]}
          </span>
          <span className="bubble-text">{text}</span>
        </div>
      )}

      {/* Tooltip */}
      {hovered && (
        <div className="seat-tooltip">
          {showPhoto && (
            <img
              src={member.photo_url}
              alt={member.name}
              className="tooltip-photo"
              loading="lazy"
            />
          )}
          <div className="tooltip-name">{member.name}</div>
          <div className="tooltip-meta">
            {member.party} · {member.state}
          </div>
          {member.role && (
            <div className="tooltip-role">{member.role}</div>
          )}
          {text && (
            <div className="tooltip-text">
              {REACTION_ICONS[reactionType]} {text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
