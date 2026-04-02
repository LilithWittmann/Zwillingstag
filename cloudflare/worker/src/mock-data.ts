import { Member, Reaction, ReactionType, Speech } from './types';

// ─── Mock speeches ────────────────────────────────────────────────────────────

export const MOCK_SPEECHES: Speech[] = [
  {
    id: 'mock_001',
    speaker_name: 'Karl Lauterbach',
    speaker_party: 'SPD',
    text:
      'Sehr geehrte Frau Präsidentin, meine Damen und Herren! ' +
      'Die Gesundheitsversorgung in Deutschland steht vor enormen Herausforderungen. ' +
      'Die Krankenhausreform, die wir jetzt auf den Weg bringen, ist längst überfällig. ' +
      'Wir werden Qualitätszentren schaffen und die Versorgung verbessern. ' +
      'Ich bin sicher, dass wir damit die richtige Richtung einschlagen. ' +
      'Die CDU/CSU hat jahrelang Reformen blockiert. Jetzt handeln wir.',
    date: '2024-03-15',
    session_id: 'session_001',
    session_title: 'Plenarsitzung 20. Wahlperiode',
    topic: 'Krankenhausreform',
  },
  {
    id: 'mock_002',
    speaker_name: 'Robert Habeck',
    speaker_party: 'GRÜNE',
    text:
      'Sehr geehrter Herr Präsident, werte Kolleginnen und Kollegen! ' +
      'Die Energiewende ist kein Luxusprojekt, sondern eine wirtschaftliche Notwendigkeit. ' +
      'Deutschland kann und muss Vorreiter bei den erneuerbaren Energien werden. ' +
      'Der Ausbau der Windkraft schreitet voran, die Solarenergie boomt. ' +
      'Wir werden die Klimaziele erreichen – entgegen allen Unkenrufen. ' +
      'Die Transformation unserer Wirtschaft schafft neue Arbeitsplätze und Wohlstand.',
    date: '2024-03-14',
    session_id: 'session_001',
    session_title: 'Plenarsitzung 20. Wahlperiode',
    topic: 'Energiewende und Klimaschutz',
  },
  {
    id: 'mock_003',
    speaker_name: 'Olaf Scholz',
    speaker_party: 'SPD',
    text:
      'Sehr geehrte Frau Präsidentin! Meine Damen und Herren! ' +
      'Deutschland steht fest an der Seite der Ukraine. ' +
      'Wir haben mehr Waffen geliefert als jedes andere europäische Land. ' +
      'Gleichzeitig setzen wir alles daran, eine Eskalation zu verhindern. ' +
      'Mein Ziel ist: Frieden in Europa – ohne Aufgabe der ukrainischen Souveränität. ' +
      'Das ist keine Schwäche, das ist verantwortungsvolle Staatskunst.',
    date: '2024-03-13',
    session_id: 'session_002',
    session_title: 'Plenarsitzung 20. Wahlperiode',
    topic: 'Ukraine-Hilfe und Außenpolitik',
  },
  {
    id: 'mock_004',
    speaker_name: 'Christian Lindner',
    speaker_party: 'FDP',
    text:
      'Herr Präsident, sehr geehrte Damen und Herren! ' +
      'Die Schuldenbremse ist kein Dogma, sie ist Vernunft. ' +
      'Wer glaubt, man könne sich dauerhaft auf Kosten künftiger Generationen finanzieren, ' +
      'der irrt. Wir brauchen Strukturreformen, keine neuen Schulden. ' +
      'Die FDP steht für Haushaltsdisziplin und wirtschaftliche Vernunft. ' +
      'Investitionen ja – aber finanziert aus Einsparungen, nicht aus Schulden.',
    date: '2024-03-12',
    session_id: 'session_002',
    session_title: 'Plenarsitzung 20. Wahlperiode',
    topic: 'Bundeshaushalt und Schuldenbremse',
  },
  {
    id: 'mock_005',
    speaker_name: 'Nancy Faeser',
    speaker_party: 'SPD',
    text:
      'Sehr geehrte Frau Präsidentin! ' +
      'Die irreguläre Migration stellt unser Land vor Herausforderungen. ' +
      'Wir handeln mit Augenmaß und humanitärer Verantwortung. ' +
      'Die Grenzkontrollen zeigen Wirkung, die Zahlen gehen zurück. ' +
      'Gleichzeitig brauchen wir legale Zuwanderung für unseren Arbeitsmarkt. ' +
      'Abschiebungen von Straftätern werden wir konsequent durchsetzen.',
    date: '2024-03-11',
    session_id: 'session_003',
    session_title: 'Plenarsitzung 20. Wahlperiode',
    topic: 'Migrationspolitik',
  },
];

export const MOCK_SESSIONS = [
  { id: 'session_001', title: '165. Sitzung', date: '2024-03-15', session_number: '165' },
  { id: 'session_002', title: '164. Sitzung', date: '2024-03-13', session_number: '164' },
  { id: 'session_003', title: '163. Sitzung', date: '2024-03-11', session_number: '163' },
];

// ─── CDU/CSU static member data ───────────────────────────────────────────────

export const STATIC_MEMBERS: Omit<Member, 'seat_row' | 'seat_col'>[] = [
  {
    id: 'merz_friedrich',
    name: 'Friedrich Merz',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'Fraktionsvorsitzender CDU/CSU',
    focus_areas: ['Wirtschaftspolitik', 'Finanzen', 'Konservative Werte'],
    political_style:
      'Konservativ, direkt, wirtschaftsliberal, rhetorisch schlagfertig. Kritisiert die Ampelregierung scharf.',
  },
  {
    id: 'doebrindt_alexander',
    name: 'Alexander Dobrindt',
    party: 'CSU',
    state: 'Bayern',
    role: 'Vorsitzender der CSU-Landesgruppe',
    focus_areas: ['Digitalisierung', 'Verkehr', 'Innenpolitik'],
    political_style: 'Bayerisch-konservativ, populistisch, lautstark.',
  },
  {
    id: 'roettgen_norbert',
    name: 'Norbert Röttgen',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'Außenpolitischer Sprecher',
    focus_areas: ['Außenpolitik', 'Europapolitik', 'Klimapolitik'],
    political_style: 'Moderater CDU-Außenpolitiker, proeuropäisch, transatlantisch orientiert.',
  },
  {
    id: 'kloeckner_julia',
    name: 'Julia Klöckner',
    party: 'CDU',
    state: 'Rheinland-Pfalz',
    role: 'Wirtschaftspolitische Sprecherin',
    focus_areas: ['Wirtschaft', 'Landwirtschaft', 'Mittelstand'],
    political_style: 'Wirtschaftsorientiert, engagiert für ländliche Regionen.',
  },
  {
    id: 'frei_thorsten',
    name: 'Thorsten Frei',
    party: 'CDU',
    state: 'Baden-Württemberg',
    role: 'Parlamentarischer Geschäftsführer',
    focus_areas: ['Rechtspolitik', 'Innenpolitik', 'Europapolitik'],
    political_style: 'Pragmatisch, sachlicher Stil, steht für konservative Rechtspolitik.',
  },
  {
    id: 'baer_dorothee',
    name: 'Dorothee Bär',
    party: 'CSU',
    state: 'Bayern',
    role: 'Digitalpolitische Sprecherin',
    focus_areas: ['Digitalisierung', 'KI', 'Technologiepolitik'],
    political_style: 'Enthusiastisch für digitale Themen, modern, kommunikativ über Social Media.',
  },
  {
    id: 'brinkhaus_ralph',
    name: 'Ralph Brinkhaus',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'MdB',
    focus_areas: ['Finanzen', 'Haushalt', 'Wirtschaft'],
    political_style: 'Erfahrener Haushaltspolitiker, sachlich, wirtschaftskompetent.',
  },
  {
    id: 'laschet_armin',
    name: 'Armin Laschet',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'MdB',
    focus_areas: ['Integrationspolitik', 'Europapolitik', 'Sozialpolitik'],
    political_style: 'Gemäßigt, integrativ, proeuropäisch. Sucht Konsens.',
  },
  {
    id: 'gueler_serap',
    name: 'Serap Güler',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'Integrationspolitische Sprecherin',
    focus_areas: ['Integration', 'Migration', 'Bildung'],
    political_style: 'Engagiert für Integration mit klarer Werteorientierung.',
  },
  {
    id: 'schoen_nadine',
    name: 'Nadine Schön',
    party: 'CDU',
    state: 'Saarland',
    role: 'Digitalpolitische Sprecherin',
    focus_areas: ['Digitalisierung', 'Familienpolitik', 'Bildung'],
    political_style: 'Zukunftsorientiert, engagiert für Familien und Digitales.',
  },
  {
    id: 'spahn_jens',
    name: 'Jens Spahn',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'Stellvertretender Fraktionsvorsitzender',
    focus_areas: ['Gesundheit', 'Sozialpolitik', 'Migration'],
    political_style: 'Ehrgeizig, konservativ-national, klare Positionen zur Migrationspolitik.',
  },
  {
    id: 'ziemiak_paul',
    name: 'Paul Ziemiak',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'MdB',
    focus_areas: ['Innenpolitik', 'Digitalpolitik', 'Junge Union'],
    political_style: 'Dynamisch, konservativ, engagiert die jüngere Generation anzusprechen.',
  },
  {
    id: 'warken_nina',
    name: 'Nina Warken',
    party: 'CDU',
    state: 'Baden-Württemberg',
    role: 'Rechtspolitische Sprecherin',
    focus_areas: ['Recht', 'Innenpolitik', 'Sicherheit'],
    political_style: 'Sachlich, rechtsstaatlich orientiert.',
  },
  {
    id: 'middelberg_mathias',
    name: 'Mathias Middelberg',
    party: 'CDU',
    state: 'Niedersachsen',
    role: 'Innen- und rechtspolitischer Sprecher',
    focus_areas: ['Innenpolitik', 'Recht', 'Migration'],
    political_style: 'Konservativ, sicherheitspolitisch engagiert.',
  },
  {
    id: 'krings_guenther',
    name: 'Günter Krings',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'MdB',
    focus_areas: ['Innenpolitik', 'Verfassungsrecht', 'Sicherheit'],
    political_style: 'Rechtspolitischer Experte, konservativ.',
  },
  {
    id: 'stegemann_albert',
    name: 'Albert Stegemann',
    party: 'CDU',
    state: 'Niedersachsen',
    role: 'Agrarpolitischer Sprecher',
    focus_areas: ['Landwirtschaft', 'Ländliche Räume', 'Ernährung'],
    political_style: 'Praxisnah, Anwalt der Landwirte.',
  },
  {
    id: 'linnemann_carsten',
    name: 'Carsten Linnemann',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'CDU-Generalsekretär / MdB',
    focus_areas: ['Wirtschaftspolitik', 'Bildung', 'Bürokratieabbau'],
    political_style: 'Unternehmerfreundlich, direkt, für weniger Bürokratie.',
  },
  {
    id: 'pilsinger_stephan',
    name: 'Stephan Pilsinger',
    party: 'CSU',
    state: 'Bayern',
    role: 'MdB',
    focus_areas: ['Gesundheit', 'Pflege', 'Sozialpolitik'],
    political_style: 'Als Arzt fachkundiger Gesundheitspolitiker, sachlich und patientenorientiert.',
  },
  {
    id: 'connemann_gitta',
    name: 'Gitta Connemann',
    party: 'CDU',
    state: 'Niedersachsen',
    role: 'Vorsitzende der Mittelstandsunion',
    focus_areas: ['Mittelstand', 'Wirtschaft', 'Verbraucherschutz'],
    political_style: 'Leidenschaftliche Anwältin des Mittelstands.',
  },
  {
    id: 'otte_henning',
    name: 'Henning Otte',
    party: 'CDU',
    state: 'Niedersachsen',
    role: 'Verteidigungspolitischer Sprecher',
    focus_areas: ['Verteidigung', 'Bundeswehr', 'Sicherheitspolitik'],
    political_style: 'Sicherheitspolitisch engagiert, Bundeswehr-Befürworter, NATO-loyal.',
  },
  {
    id: 'amthor_philipp',
    name: 'Philipp Amthor',
    party: 'CDU',
    state: 'Mecklenburg-Vorpommern',
    role: 'MdB',
    focus_areas: ['Innenpolitik', 'Recht', 'Digitalisierung'],
    political_style: 'Jung und konservativ, rhetorisch versiert.',
  },
  {
    id: 'schuster_armin',
    name: 'Armin Schuster',
    party: 'CDU',
    state: 'Baden-Württemberg',
    role: 'MdB',
    focus_areas: ['Innenpolitik', 'Bundespolizei', 'Grenzschutz'],
    political_style: 'Sicherheitspolitisch konservativ, klare Linie bei innerer Sicherheit.',
  },
  {
    id: 'jung_andreas',
    name: 'Andreas Jung',
    party: 'CDU',
    state: 'Baden-Württemberg',
    role: 'Klimaschutzpolitischer Sprecher',
    focus_areas: ['Klimaschutz', 'Energie', 'Umwelt'],
    political_style: 'CDU-intern für ambitionierten Klimaschutz, marktwirtschaftliche Lösungen.',
  },
  {
    id: 'czaja_mario',
    name: 'Mario Czaja',
    party: 'CDU',
    state: 'Berlin',
    role: 'MdB',
    focus_areas: ['Soziales', 'Migration', 'Gesundheit'],
    political_style: 'Berliner CDU, sozial ausgerichtet, pragmatisch.',
  },
  {
    id: 'haase_christian',
    name: 'Christian Haase',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'Haushaltspolitischer Sprecher',
    focus_areas: ['Haushalt', 'Finanzen', 'Kommunalpolitik'],
    political_style: 'Solider Haushälter, für Schuldenbremse und fiskalische Disziplin.',
  },
  {
    id: 'kaufmann_stefan',
    name: 'Stefan Kaufmann',
    party: 'CDU',
    state: 'Baden-Württemberg',
    role: 'MdB',
    focus_areas: ['Forschung', 'Technologie', 'Innovation'],
    political_style: 'Technologieaffin, innovationsorientiert.',
  },
  {
    id: 'lehrieder_paul',
    name: 'Paul Lehrieder',
    party: 'CSU',
    state: 'Bayern',
    role: 'MdB',
    focus_areas: ['Sport', 'Soziales', 'Jugend'],
    political_style: 'Sportpolitisch engagiert, volksnaher bayerischer Politiker.',
  },
  {
    id: 'steiniger_johannes',
    name: 'Johannes Steiniger',
    party: 'CDU',
    state: 'Rheinland-Pfalz',
    role: 'MdB',
    focus_areas: ['Digitalpolitik', 'Wirtschaft', 'Mittelstand'],
    political_style: 'Jung und unternehmerisch, treibt digitale Agenda voran.',
  },
  {
    id: 'radtke_kerstin',
    name: 'Kerstin Radomski',
    party: 'CDU',
    state: 'Nordrhein-Westfalen',
    role: 'MdB',
    focus_areas: ['Familie', 'Soziales', 'Senioren'],
    political_style: 'Familienpolitisch engagiert, Generationengerechtigkeit.',
  },
  {
    id: 'weisgerber_anja',
    name: 'Anja Weisgerber',
    party: 'CSU',
    state: 'Bayern',
    role: 'MdB',
    focus_areas: ['Umwelt', 'Chemie', 'Verbraucherschutz'],
    political_style: 'Umweltpolitisch aktiv innerhalb CSU-Linie, pragmatisch.',
  },
];

// ─── Mock reactions ───────────────────────────────────────────────────────────

export function generateMockReactions(members: Member[], speech: Speech | null): Reaction[] {
  const ownFactionSpeaking =
    !!speech?.speaker_party &&
    ['CDU', 'CSU', 'CDU/CSU'].includes(speech.speaker_party.toUpperCase());

  // deterministic seeded random based on speech id
  let seed = speech ? hashCode(speech.id) : 42;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) & 0xffffffff;
    return ((seed >>> 0) / 0xffffffff);
  };
  const pick = <T>(arr: T[]): T => arr[Math.floor(rnd() * arr.length)];

  const remarks = [
    'Hören Sie doch auf!',
    'Das glauben Sie doch selbst nicht!',
    'Das ist doch absurd!',
    'Schämen Sie sich!',
    'Und die Fakten?',
    'Sehr fragwürdig!',
    'Das ist falsch!',
    'Eine Katastrophe!',
  ];
  const questions = [
    'Wann legen Sie endlich konkrete Zahlen vor?',
    'Welche Alternativen haben Sie geprüft?',
    'Wie erklären Sie das den Bürgerinnen?',
    'Was kostet das den Steuerzahler?',
  ];

  return members.map((m) => {
    const roll = rnd();
    if (ownFactionSpeaking) {
      if (roll < 0.6) {
        return { member_id: m.id, reaction_type: 'clap' as ReactionType, intensity: 3 + Math.floor(rnd() * 3), text: null };
      } else if (roll < 0.75) {
        return { member_id: m.id, reaction_type: 'remark' as ReactionType, intensity: 1, text: pick(['Sehr gut!', 'Richtig so!', 'Sehr wahr!', 'Bravo!', 'Genau!']) };
      }
      return { member_id: m.id, reaction_type: 'silent' as ReactionType, intensity: 1, text: null };
    } else {
      if (roll < 0.08) {
        return { member_id: m.id, reaction_type: 'clap' as ReactionType, intensity: 1 + Math.floor(rnd() * 2), text: null };
      } else if (roll < 0.30) {
        return { member_id: m.id, reaction_type: 'remark' as ReactionType, intensity: 1, text: pick(remarks) };
      } else if (roll < 0.42) {
        return { member_id: m.id, reaction_type: 'question' as ReactionType, intensity: 1, text: pick(questions) };
      }
      return { member_id: m.id, reaction_type: 'silent' as ReactionType, intensity: 1, text: null };
    }
  });
}

function hashCode(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  }
  return h;
}
