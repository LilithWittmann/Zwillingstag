/**
 * Seat-assignment helper – mirrors the Python DebateSimulator._assign_seats logic.
 */
import { Member } from './types';
import { STATIC_MEMBERS } from './mock-data';

export function assignSeats(members: Omit<Member, 'seat_row' | 'seat_col'>[]): Member[] {
  const n = members.length;
  const rowSizes: number[] = [];
  let remaining = n;
  const colsInFirstRow = Math.max(6, Math.floor(n / 6));
  let row = 0;
  while (remaining > 0) {
    const size = Math.min(colsInFirstRow + row * 2, remaining);
    rowSizes.push(size);
    remaining -= size;
    row++;
  }

  const result: Member[] = [];
  let idx = 0;
  for (let rowIdx = 0; rowIdx < rowSizes.length; rowIdx++) {
    for (let colIdx = 0; colIdx < rowSizes[rowIdx]; colIdx++) {
      if (idx >= n) break;
      result.push({ ...members[idx], seat_row: rowIdx, seat_col: colIdx } as Member);
      idx++;
    }
  }
  return result;
}

export function getStaticMembers(): Member[] {
  return assignSeats(STATIC_MEMBERS);
}
