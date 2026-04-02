import React, { useMemo } from 'react'
import MemberSeat from './MemberSeat'

/**
 * Renders the CDU/CSU faction in a semi-circular parliament layout.
 * Members are arranged in arcs, front rows closer to the speaker podium.
 */
export default function ParliamentView({ members, reactions }) {
  const reactionMap = useMemo(() => {
    const map = {}
    if (reactions) {
      for (const r of reactions) {
        map[r.member_id] = r
      }
    }
    return map
  }, [reactions])

  // Group members by row
  const rowMap = useMemo(() => {
    const rows = {}
    for (const m of members) {
      const row = m.seat_row ?? 0
      if (!rows[row]) rows[row] = []
      rows[row].push(m)
    }
    return rows
  }, [members])

  const numRows = Object.keys(rowMap).length

  // SVG dimensions
  const svgWidth = 900
  const svgHeight = 480
  const cx = svgWidth / 2
  const cy = svgHeight + 60  // center point below the visible area → creates upper arc
  const innerRadius = 200
  const rowSpacing = 52

  const seats = useMemo(() => {
    const result = []
    const rows = Object.keys(rowMap)
      .map(Number)
      .sort((a, b) => a - b)

    for (const row of rows) {
      const members = rowMap[row]
      const radius = innerRadius + row * rowSpacing
      const n = members.length
      // Arc from ~190° to 350° (semi-circle open at bottom)
      const startAngle = Math.PI + 0.18
      const endAngle = 2 * Math.PI - 0.18
      const totalAngle = endAngle - startAngle

      members.forEach((m, i) => {
        const fraction = n === 1 ? 0.5 : i / (n - 1)
        const angle = startAngle + fraction * totalAngle
        const x = cx + radius * Math.cos(angle)
        const y = cy + radius * Math.sin(angle)
        result.push({ member: m, x, y })
      })
    }
    return result
  }, [rowMap])

  return (
    <div className="parliament-container">
      <div className="parliament-label">CDU / CSU Fraktion</div>
      <svg
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="parliament-svg"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Arc guides (subtle background lines) */}
        {Array.from({ length: numRows }, (_, row) => {
          const radius = innerRadius + row * rowSpacing
          const startAngle = Math.PI + 0.18
          const endAngle = 2 * Math.PI - 0.18
          const x1 = cx + radius * Math.cos(startAngle)
          const y1 = cy + radius * Math.sin(startAngle)
          const x2 = cx + radius * Math.cos(endAngle)
          const y2 = cy + radius * Math.sin(endAngle)
          const d = `M ${x1} ${y1} A ${radius} ${radius} 0 0 1 ${x2} ${y2}`
          return (
            <path
              key={`arc-${row}`}
              d={d}
              fill="none"
              stroke="rgba(255,255,255,0.04)"
              strokeWidth="1"
            />
          )
        })}

        {/* Speaker podium indicator */}
        <ellipse
          cx={cx}
          cy={svgHeight - 18}
          rx={60}
          ry={14}
          fill="rgba(200,170,80,0.15)"
          stroke="rgba(200,170,80,0.4)"
          strokeWidth="1"
        />
        <text
          x={cx}
          y={svgHeight - 14}
          textAnchor="middle"
          fontSize="10"
          fill="rgba(200,170,80,0.7)"
          fontFamily="Inter, sans-serif"
        >
          Rednerpult
        </text>

        {/* Member seats rendered as foreignObject */}
        {seats.map(({ member, x, y }) => (
          <foreignObject
            key={member.id}
            x={x - 19}
            y={y - 19}
            width={38}
            height={38}
            overflow="visible"
          >
            <MemberSeat
              member={member}
              reaction={reactionMap[member.id]}
            />
          </foreignObject>
        ))}
      </svg>
    </div>
  )
}
