import React from 'react'

export default function ReactionLegend() {
  return (
    <div className="reaction-legend">
      <div className="legend-item">
        <span className="legend-icon clap-icon">👏</span>
        <span>Applaus</span>
      </div>
      <div className="legend-item">
        <span className="legend-icon">💬</span>
        <span>Zwischenruf</span>
      </div>
      <div className="legend-item">
        <span className="legend-icon">❓</span>
        <span>Zwischenfrage</span>
      </div>
    </div>
  )
}
