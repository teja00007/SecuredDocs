"use client";

import { Suspense, useEffect, useRef, useState, KeyboardEvent, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { isAuthenticated, getAccessToken } from "@/lib/auth";
import { api } from "@/lib/api";
import MarkdownMessage from "@/components/MarkdownMessage";
import LinkPreviewCard from "@/components/LinkPreviewCard";
import { usePresence } from "@/hooks/usePresence";
import type { User } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
function getWsBase() {
  if (API_BASE) return API_BASE.replace(/^http/, "ws");
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}`;
}

// ── Types ─────────────────────────────────────────────────────────────────────
interface Channel {
  id: string; name: string; type: string;
  created_by: string | null; member_count: number;
  dm_partner_id?: string | null; dm_partner_username?: string | null;
}

interface Reaction { emoji: string; count: number; users: string[] }

interface ChatMessage {
  id: string; channel_id: string;
  sender_id: string; sender_username: string;
  content: string; created_at: string;
  edited_at?: string | null;
  thread_count?: number;
  parent_id?: string | null;
  reactions?: Reaction[];
  pinned?: boolean;
}

interface ChannelMember {
  user_id: string; username: string; email: string; joined_at: string;
}
interface OrgUser { id: string; username: string; email: string; }
interface RagHistoryItem {
  query: string;
  answer: string;
  sources: { document_id: string; filename: string; chunk_text: string; score: number }[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function timeStr(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function dateSep(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}
function sameGroup(a: ChatMessage, b: ChatMessage): boolean {
  if (a.sender_id !== b.sender_id) return false;
  return Math.abs(new Date(b.created_at).getTime() - new Date(a.created_at).getTime()) < 3 * 60 * 1000;
}
function avatarColor(name: string): string {
  const colors = ["#6366f1","#8b5cf6","#ec4899","#f97316","#10b981","#0ea5e9","#14b8a6","#f59e0b"];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}
function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// File attachment link pattern: [📎 filename](doc:id)
const FILE_LINK_RE = /\[📎 ([^\]]+)\]\(doc:([^)]+)\)/g;
// Inline image pattern: (img:url)
const IMG_LINK_RE = /\(img:([^)]+)\)/g;

// ── Emoji data ────────────────────────────────────────────────────────────────
const EMOJI_CATEGORIES: Record<string, string[]> = {
  "Smileys": [
    "😀","😃","😄","😁","😆","😅","😂","🤣","🥲","😊","😇","🙂","🙃","😉","😌","😍","🥰","😘","😗","😙","😚","😋","😛","😝","😜","🤪","🤨","🧐","🤓","😎","🥸","🤩","🥳","😏","😒","😞","😔","😟","😕","🙁","☹️","😣","😖","😫","😩","🥺","😢","😭","😤","😠","😡","🤬","🤯","😳","🥵","🥶","😱","😨","😰","😥","😓","🤗","🤔","🤭","🤫","🤥","😶","😑","😬","🙄","😯","😦","😧","😮","😲","🥱","😴","🤤","😪","😵","🤐","🥴","🤢","🤮","🤧","😷","🤒","🤕","🤑","🤠","😈","👿","👹","👺","💀","☠️","👻","👽","👾","🤖","💩","😺","😸","😹","😻","😼","😽","🙀","😿","😾",
  ],
  "People": [
    "👶","🧒","👦","👧","🧑","👱","👨","🧔","👩","🧓","👴","👵","👮","🕵️","💂","🥷","👷","🫅","🤴","👸","👰","🤵","🙍","🙎","🙅","🙆","💁","🙋","🧏","🙇","🤦","🤷","👼","🎅","🤶","🧑‍🎄","🦸","🦹","🧙","🧝","🧛","🧟","🧌","🧞","🧜","🧚","🧑‍🤝‍🧑","👫","👬","👭","💏","💑","👨‍👩‍👦","👨‍👩‍👧","👨‍👩‍👧‍👦","👩‍👦","👩‍👧","👨‍👦","👨‍👧",
  ],
  "Gestures": [
    "👋","🤚","🖐","✋","🖖","🫱","🫲","🫳","🫴","👌","🤌","🤏","✌️","🤞","🤟","🤘","🤙","👈","👉","👆","🖕","👇","☝️","🫵","👍","👎","✊","👊","🤛","🤜","👏","🙌","🫶","👐","🤲","🤝","🙏","✍️","💅","🤳","💪","🦾","🦿","🦵","🦶","👂","🦻","👃","🧠","🫀","🫁","🦷","🦴","👀","👅","💋","👣",
  ],
  "Nature": [
    "🌸","🌺","🌻","🌹","🥀","🌷","🌼","💐","🍀","☘️","🌿","🌱","🌲","🌳","🌴","🌵","🎋","🎍","🍁","🍂","🍃","🍄","🌾","💫","⭐","🌟","✨","💥","🔥","🌈","⛅","🌤","⛈","🌩","🌨","❄️","💧","🌊","🌀","🌪","🌫","☁️","🌙","🌛","🌜","🌝","🌞","🌑","🌒","🌓","🌔","🌕","🌖","🌗","🌘","🐶","🐱","🐭","🐹","🐰","🦊","🐻","🐼","🐻‍❄️","🐨","🐯","🦁","🐮","🐷","🐸","🐵","🙈","🙉","🙊","🐔","🐧","🐦","🦆","🦅","🦉","🦇","🐺","🐗","🦄","🐝","🪱","🐛","🦋","🐌","🐞","🐜","🪲","🦟","🦗","🕷","🦂","🐢","🐍","🦎","🦖","🦕","🐙","🦑","🦐","🦞","🦀","🐡","🐠","🐟","🐬","🐳","🦈","🦭","🦁","🐆","🐅","🦒","🦓","🦍","🦧","🦣","🐘","🦛","🦏","🐪","🐫","🦙","🦘","🦥","🦦","🦨","🦡",
  ],
  "Food": [
    "🍎","🍏","🍊","🍋","🍌","🍍","🥭","🍑","🍒","🍓","🫐","🥝","🍅","🫒","🥥","🥑","🍆","🥔","🥕","🌽","🌶","🫑","🥒","🥬","🥦","🧄","🧅","🍄","🥜","🫘","🌰","🍞","🥐","🥖","🫓","🥨","🥯","🧀","🥚","🍳","🧈","🥞","🧇","🥓","🥩","🍗","🍖","🌭","🍔","🍟","🍕","🫔","🥪","🥙","🧆","🌮","🌯","🥗","🥘","🫕","🍝","🍜","🍲","🍛","🍣","🍱","🥟","🦪","🍤","🍙","🍚","🍘","🍥","🥮","🍡","🧁","🍰","🎂","🍮","🍭","🍬","🍫","🍿","🍩","🍪","🌰","🥜","🍯","🧃","🥤","🧋","☕","🍵","🫖","🧉","🍺","🍻","🥂","🍷","🥃","🍸","🍹","🍾","🧊","🥄","🍴","🍽",
  ],
  "Activities": [
    "⚽","🏀","🏈","⚾","🥎","🏐","🏉","🎾","🥏","🎱","🏓","🏸","🏒","🏑","🥍","🏏","🪃","🥅","⛳","🎣","🤿","🎽","🎿","🛷","🥌","🎯","🪀","🪁","🎣","🤸","🤼","🤺","🤾","🏌","🧘","🧗","🏋","🚴","🏊","🛹","🛼","🛻","🧜","⛷","🏇","🏄","🚵","🚴","🎠","🎡","🎢","🎪","🎭","🎨","🖼","🎰","🎲","🧩","🎮","🕹","🎯","🎱","🎳","🎻","🎸","🎹","🎷","🎺","🥁","🪘","🎤","🎧","🎼","🎬","🎥","📽","🎞","📺","📻","📷","📸","🎙","🎚","🎛","🏆","🥇","🥈","🥉","🎖","🏅","🎗","🎁","🎀","🎊","🎉","🎈","🎆","🎇","🎃","🎄","🎋","🎍","🎑","🧧","🪔","🧨","🎐","🎏","🎎",
  ],
  "Travel": [
    "🚗","🚕","🚙","🚌","🚎","🏎","🚓","🚑","🚒","🚐","🛻","🚚","🚛","🚜","🏍","🛵","🚲","🛴","🛺","🚨","🚔","🚍","🚘","🚖","🚡","🚠","🚟","🚃","🚋","🚞","🚝","🚄","🚅","🚈","🚂","🚆","🚇","🚊","🚉","✈️","🛫","🛬","🛩","💺","🛸","🚀","🛶","⛵","🚤","🛥","🛳","⛴","🚢","🪂","⛽","🚧","🚦","🚥","🗺","🧭","⛰","🌋","🏔","🗻","🏕","🏖","🏜","🏝","🏞","🏟","🏛","🏗","🏘","🏚","🏠","🏡","🏢","🏣","🏤","🏥","🏦","🏨","🏩","🏪","🏫","🏭","🏯","🏰","💒","🗼","🗽","⛪","🕌","🛕","🕍","⛩","🕋","⛲","⛺","🌁","🌃","🏙","🌄","🌅","🌆","🌇","🌉","🌌","🎠","🎡","🎢",
  ],
  "Objects": [
    "⌚","📱","📲","💻","⌨️","🖥","🖨","🖱","🖲","🕹","🗜","💾","💿","📀","📼","📷","📸","📹","🎥","📽","🎞","📞","☎️","📟","📠","📺","📻","🧭","⏱","⏲","⏰","🕰","⌛","⏳","📡","🔋","🔌","💡","🔦","🕯","🪔","🧯","🛢","💸","💵","💴","💶","💷","🪙","💰","💳","💎","⚖️","🪜","🧰","🪛","🔧","🔨","⚒","🛠","⛏","🪚","🔩","⚙️","🪤","🧱","🪞","🛋","🚪","🪑","🚽","🪠","🚿","🛁","🧴","🧷","🧹","🧺","🧻","🪣","🧼","🪥","🧽","🪒","🧲","🪜","🛒","🚬","⚰️","⚱️","🪬","🧿","💈","⚗️","🔭","🔬","🩺","🩹","💊","💉","🩸","🌡","🧬","🦠","🧫","🧪","🩻","🛏","🛁","🪑","🧳","🌂","☂️","🧵","🪡","🧶","🪢","👓","🕶","🥽","🧥","🥼","👔","👕","👖","🩱","👗","👘","🥻","🩴","🥿","👠","👡","👢","👞","👟","🥾","🧤","🧣","🎩","🧢","👒","⛑","💄","💍","💼","🎒","🧳",
  ],
  "Symbols": [
    "❤️","🧡","💛","💚","💙","💜","🖤","🤍","🤎","💔","❤️‍🔥","❤️‍🩹","💞","💕","💓","💗","💖","💘","💝","💟","♾️","✅","❌","⚠️","❗","❓","‼️","⁉️","🔴","🟠","🟡","🟢","🔵","🟣","⚫","⚪","🟤","🔶","🔷","🔸","🔹","🔺","🔻","💠","🔘","🔲","🔳","▪️","▫️","◾","◽","◼️","◻️","🟥","🟧","🟨","🟩","🟦","🟪","⬛","⬜","🟫","💯","🔢","🔣","🔤","🔡","🔠","🆕","🆙","🆒","🆓","🆖","🆗","🆙","🆘","🆚","🉐","🈹","🈵","🈲","🈴","🈺","🈷️","✴️","🆚","💮","🉑","㊙️","㊗️","🈶","🈚","🈸","🈺","🈷️","✳️","❎","🌐","💠","🔔","🔕","📣","📢","🎵","🎶","🔇","🔈","🔉","🔊","📯","🔔","🔕","🔁","🔂","🔀","⏩","⏪","⏫","⏬","⏭","⏮","⏯","⏹","⏺","⏏️","⬆️","⬇️","⬅️","➡️","↗️","↘️","↙️","↖️","↕️","↔️","↩️","↪️","⤴️","⤵️","🔃","🔄","🔙","🔚","🔛","🔜","🔝","🚫","⛔","🚳","🚭","🚯","🚱","🚷","📵","🔞","☢️","☣️","✔️","☑️","♻️","⚜️","🔱","📛","🔰","♾","⭕","🔟","🔠","🔡","🔢","🔣","🔤","🅰️","🅱️","🆎","🆑","🅾️","🆘","❎","➕","➖","➗","✖️","♾️","💲","💱","🔚","🔙","🔛","🔜","🔝","🔯","✡️","⚛️","🕉","✝️","☦️","☪️","☮️","🛐","♈","♉","♊","♋","♌","♍","♎","♏","♐","♑","♒","♓","⛎","🔯","⚕️","♻️","⚜️","🏧","💹","❇️","✳️","❎","⭕","🚩","🏁","🏳️","🏴",
  ],
};

// Emoji names for search (keyword → emoji mapping)
const EMOJI_SEARCH: [string, string][] = [
  ["smile grin happy","😀"],["laugh joy lol tears funny","😂"],["heart love red","❤️"],["thumbs up like good yes","👍"],
  ["thumbs down dislike no bad","👎"],["party celebrate congrats","🎉"],["fire hot trending","🔥"],["100 perfect score","💯"],
  ["eyes see looking","👀"],["think thinking hmm","🤔"],["cry sad tears","😢"],["wow surprise amazing","😮"],
  ["pray thanks please","🙏"],["clap applause bravo","👏"],["rocket launch fast","🚀"],["check done ok yes","✅"],
  ["cross no wrong x","❌"],["warning alert careful","⚠️"],["idea light bulb","💡"],["note write memo","📝"],
  ["key important","🔑"],["target goal aim","🎯"],["strong muscle flex","💪"],["star awesome great","🌟"],
  ["handshake deal agree","🤝"],["love eyes heart","😍"],["sunglasses cool","😎"],["explode mind blown","🤯"],
  ["wave hello bye","👋"],["dog puppy","🐶"],["cat kitty","🐱"],["pizza food","🍕"],["coffee morning","☕"],
  ["beer drink cheers","🍺"],["cake birthday dessert","🎂"],["rainbow colorful","🌈"],["sun sunny bright","☀️"],
  ["moon night","🌙"],["snow cold winter","❄️"],["tree nature green","🌲"],["flower pretty","🌸"],
  ["car drive","🚗"],["plane travel fly","✈️"],["house home","🏠"],["money cash","💰"],["phone mobile","📱"],
  ["computer laptop","💻"],["email mail","📧"],["clock time","⏰"],["calendar date","📅"],["book read","📚"],
  ["music note song","🎵"],["sport soccer football","⚽"],["basketball","🏀"],["trophy win","🏆"],
  ["sad cry sob","😭"],["angry mad","😡"],["scared fear ghost","👻"],["sick ill","😷"],["cool chill","😎"],
  ["nerd smart glasses","🤓"],["robot ai","🤖"],["alien","👽"],["skull dead","💀"],["angel","😇"],
  ["devil evil","😈"],["monkey","🐵"],["pig","🐷"],["cow","🐮"],["frog","🐸"],["rabbit bunny","🐰"],
  ["bear","🐻"],["chicken","🐔"],["fish","🐟"],["snake","🐍"],["butterfly","🦋"],
  ["red heart","❤️"],["orange heart","🧡"],["yellow heart","💛"],["green heart","💚"],["blue heart","💙"],
  ["purple heart","💜"],["broken heart","💔"],["sparkling heart","💖"],["love letter","💌"],
  ["ok hand","👌"],["peace","✌️"],["crossed fingers luck","🤞"],["metal rock","🤘"],["point right","👉"],
  ["point left","👈"],["point up","👆"],["point down","👇"],["raised hand","✋"],["folded hands namaste","🙏"],
  ["facepalm","🤦"],["shrug","🤷"],["flex strong arm","💪"],["hug","🤗"],["think","🤔"],
];

function searchEmojis(query: string): string[] {
  const q = query.toLowerCase().trim();
  if (!q) return [];
  const results: string[] = [];
  const seen = new Set<string>();
  // Exact emoji character match
  for (const [keywords, emoji] of EMOJI_SEARCH) {
    if (keywords.split(" ").some(k => k.startsWith(q)) && !seen.has(emoji)) {
      results.push(emoji); seen.add(emoji);
    }
  }
  // Partial keyword match
  for (const [keywords, emoji] of EMOJI_SEARCH) {
    if (keywords.includes(q) && !seen.has(emoji)) {
      results.push(emoji); seen.add(emoji);
    }
  }
  // Also search through all emojis if few results
  if (results.length < 6) {
    const all = Object.values(EMOJI_CATEGORIES).flat();
    for (const e of all) {
      if (!seen.has(e)) { results.push(e); seen.add(e); if (results.length >= 60) break; }
    }
  }
  return results;
}

const RECENTLY_USED_KEY = "nexus_emoji_recent";
function getRecentEmojis(): string[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(RECENTLY_USED_KEY) || "[]"); }
  catch { return []; }
}
function addRecentEmoji(emoji: string) {
  if (typeof window === "undefined") return;
  try {
    const recent = getRecentEmojis().filter(e => e !== emoji);
    recent.unshift(emoji);
    localStorage.setItem(RECENTLY_USED_KEY, JSON.stringify(recent.slice(0, 24)));
  } catch { /* ignore */ }
}

const CATEGORY_ICONS: Record<string, string> = {
  "Recent": "🕐", "Smileys": "😀", "People": "🧑", "Gestures": "👋",
  "Nature": "🌿", "Food": "🍔", "Activities": "⚽", "Travel": "✈️",
  "Objects": "💡", "Symbols": "💯",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function PresenceDot({ status }: { status: "online" | "away" | "dnd" | "offline" }) {
  const color =
    status === "online" ? "bg-emerald-500" :
    status === "away"   ? "bg-yellow-400"  :
    status === "dnd"    ? "bg-yellow-400"  :
                          "bg-gray-300";
  return (
    <span className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white ${color}`} />
  );
}

function EmojiPicker({
  onSelect, onClose, alignRight,
}: {
  onSelect: (emoji: string) => void;
  onClose: () => void;
  alignRight?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState("Recent");
  const [recentEmojis, setRecentEmojis] = useState<string[]>([]);

  useEffect(() => {
    setRecentEmojis(getRecentEmojis());
    setTimeout(() => searchRef.current?.focus(), 30);
  }, []);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const categories = ["Recent", ...Object.keys(EMOJI_CATEGORIES)];

  const displayEmojis: string[] = (() => {
    if (search.trim()) return searchEmojis(search.trim());
    if (activeCategory === "Recent") return recentEmojis;
    return EMOJI_CATEGORIES[activeCategory] ?? [];
  })();

  const sectionLabel = search.trim()
    ? `Results for "${search}"`
    : activeCategory;

  function handleSelect(emoji: string) {
    addRecentEmoji(emoji);
    setRecentEmojis(getRecentEmojis());
    onSelect(emoji);
    onClose();
  }

  return (
    <div
      ref={ref}
      className={`absolute z-50 top-full mt-1 w-[360px] rounded-2xl border border-gray-200 bg-white shadow-2xl overflow-hidden flex flex-col ${
        alignRight ? "right-0" : "left-0"
      }`}
      style={{ maxHeight: 420 }}
    >
      {/* Search bar */}
      <div className="px-3 pt-3 pb-2 flex items-center gap-2 border-b border-gray-100">
        <div className="flex flex-1 items-center gap-2 rounded-xl border-2 border-indigo-400 bg-white px-3 py-2 focus-within:border-indigo-500">
          <svg className="h-4 w-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 0 5 11a6 6 0 0 0 12 0z" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Find something fun"
            className="flex-1 bg-transparent text-sm text-gray-700 placeholder-gray-400 outline-none"
          />
        </div>
        <button className="shrink-0 text-2xl hover:scale-110 transition-transform" title="Emoji styles">🎭</button>
      </div>

      {/* Section label */}
      <p className="px-4 pt-2.5 pb-1 text-sm font-semibold text-gray-700">{sectionLabel}</p>

      {/* Emoji grid — scrollable */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {displayEmojis.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400">
            {search.trim() ? "No emojis found" : "No recently used emojis"}
          </p>
        ) : (
          <div className="grid grid-cols-6 gap-0">
            {displayEmojis.map((emoji, i) => (
              <button
                key={`${emoji}-${i}`}
                onClick={() => handleSelect(emoji)}
                className="flex h-14 w-full items-center justify-center rounded-xl text-3xl hover:bg-gray-100 active:scale-90 transition-all duration-75"
                title={emoji}
              >
                {emoji}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Category tabs — always at the bottom */}
      <div className="flex items-center border-t border-gray-100 bg-gray-50 px-1 py-1">
        {categories.map(cat => (
          <button
            key={cat}
            onClick={() => { setActiveCategory(cat); setSearch(""); }}
            title={cat}
            className={`flex flex-1 items-center justify-center py-1.5 rounded-lg text-xl transition-colors ${
              activeCategory === cat && !search.trim()
                ? "bg-white shadow-sm text-gray-900"
                : "text-gray-400 hover:bg-white hover:text-gray-700"
            }`}
          >
            {CATEGORY_ICONS[cat] ?? "🙂"}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── File attachment preview chip ──────────────────────────────────────────────
interface AttachmentChip {
  file: File;
  previewUrl?: string; // For images
}

function CircularProgress({ pct }: { pct: number }) {
  const r = 20;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  return (
    <svg className="absolute inset-0 w-full h-full" viewBox="0 0 48 48">
      {/* Track */}
      <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="4" />
      {/* Progress arc */}
      <circle
        cx="24" cy="24" r={r}
        fill="none"
        stroke="white"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        style={{ transform: "rotate(-90deg)", transformOrigin: "50% 50%", transition: "stroke-dashoffset 0.2s ease" }}
      />
      {/* Percentage text */}
      <text x="24" y="28" textAnchor="middle" fill="white" fontSize="11" fontWeight="bold">{pct}%</text>
    </svg>
  );
}

function AttachmentChipView({
  chip, onRemove, uploadProgress,
}: {
  chip: AttachmentChip;
  onRemove: () => void;
  uploadProgress?: number | null;
}) {
  const isUploading = uploadProgress !== null && uploadProgress !== undefined;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
      {chip.previewUrl ? (
        <div className="relative h-12 w-12 shrink-0 rounded overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={chip.previewUrl} alt={chip.file.name} className="h-full w-full object-cover" />
          {/* Circular progress overlay */}
          {isUploading && (
            <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
              <CircularProgress pct={uploadProgress!} />
            </div>
          )}
        </div>
      ) : (
        <div className="relative h-10 w-10 shrink-0 flex items-center justify-center rounded bg-slate-100">
          <span className="text-lg">📎</span>
          {isUploading && (
            <div className="absolute inset-0 rounded bg-indigo-600/80 flex items-center justify-center">
              <CircularProgress pct={uploadProgress!} />
            </div>
          )}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-slate-700 max-w-[140px]">{chip.file.name}</p>
        <p className="text-slate-400">
          {isUploading ? `Uploading… ${uploadProgress}%` : formatBytes(chip.file.size)}
        </p>
      </div>
      {!isUploading && (
        <button onClick={onRemove} className="ml-1 shrink-0 text-slate-400 hover:text-red-500 transition-colors">✕</button>
      )}
    </div>
  );
}

// Detect the first bare https:// URL in a text string (not inside markdown links)
const _BARE_URL_RE = /https?:\/\/[^\s<>"')\]]+/;
function extractFirstUrl(text: string): string | null {
  const m = _BARE_URL_RE.exec(text);
  return m ? m[0] : null;
}

// Render message content with file link and inline image detection
function MessageContent({ content, inverted, channelId }: { content: string; inverted: boolean; channelId: string }) {
  type Part =
    | { type: "text"; text: string }
    | { type: "file"; filename: string; docId: string }
    | { type: "img"; url: string };

  const parts: Part[] = [];
  // Combined regex: file links and image links
  const combined = new RegExp(`${FILE_LINK_RE.source}|${IMG_LINK_RE.source}`, "g");
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = combined.exec(content)) !== null) {
    if (match.index > last) parts.push({ type: "text", text: content.slice(last, match.index) });
    if (match[1] && match[2]) {
      // file link
      parts.push({ type: "file", filename: match[1], docId: match[2] });
    } else if (match[3]) {
      // image link
      parts.push({ type: "img", url: match[3] });
    }
    last = match.index + match[0].length;
  }
  if (last < content.length) parts.push({ type: "text", text: content.slice(last) });

  // Detect a bare URL for link preview (only for non-inverted/received messages to avoid clutter)
  const previewUrl = !inverted ? extractFirstUrl(content) : null;

  if (parts.length === 0 || (parts.length === 1 && parts[0].type === "text")) {
    return (
      <div>
        <MarkdownMessage content={content} inverted={inverted} />
        {previewUrl && <LinkPreviewCard url={previewUrl} />}
      </div>
    );
  }

  return (
    <div className="text-sm">
      {parts.map((p, i) => {
        if (p.type === "text") return p.text ? <MarkdownMessage key={i} content={p.text} inverted={inverted} /> : null;
        if (p.type === "img") {
          const src = p.url.startsWith("http") ? p.url : `${API_BASE}${p.url}`;
          return (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={i} src={src} alt="uploaded image"
              className="mt-1 max-w-xs max-h-64 rounded-lg object-contain cursor-pointer"
              onClick={() => window.open(src, "_blank")} />
          );
        }
        const downloadUrl = `${API_BASE}/api/v1/documents/${p.docId}/download`;
        return (
          <a key={i} href={downloadUrl}
            target="_blank" rel="noopener noreferrer"
            className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium border transition-colors ${
              inverted
                ? "border-white/30 text-white hover:bg-white/20"
                : "border-slate-200 text-indigo-600 hover:bg-indigo-50"
            }`}>
            <span>📎</span>{p.filename}
          </a>
        );
      })}
      {previewUrl && <LinkPreviewCard url={previewUrl} />}
    </div>
  );
}

// ── Thread Panel ──────────────────────────────────────────────────────────────
function ThreadPanel({
  rootMsg, channelId, currentUserId, onClose, onThreadReply,
}: {
  rootMsg: ChatMessage;
  channelId: string;
  currentUserId: string;
  onClose: () => void;
  onThreadReply: (parentId: string) => void;
}) {
  const [replies, setReplies] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setLoading(true);
    api.get<{ root: ChatMessage; replies: ChatMessage[] }>(
      `/api/v1/chat/channels/${channelId}/messages/${rootMsg.id}/thread`
    )
      .then(data => setReplies(data.replies ?? []))
      .catch(() => setReplies([]))
      .finally(() => setLoading(false));
    setTimeout(() => inputRef.current?.focus(), 100);
  }, [channelId, rootMsg.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [replies]);

  async function sendReply() {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const msg = await api.post<ChatMessage>(`/api/v1/chat/channels/${channelId}/messages`, {
        content: text,
        parent_id: rootMsg.id,
      });
      setReplies(prev => [...prev, msg]);
      setInput("");
      onThreadReply(rootMsg.id);
    } catch { /* ignore */ } finally {
      setSending(false);
    }
  }

  const isMe = (msg: ChatMessage) => msg.sender_id === currentUserId;

  return (
    <div className="flex flex-col w-[380px] shrink-0 border-l border-slate-200 bg-white h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 shrink-0">
        <h3 className="text-sm font-semibold text-slate-800">Thread</h3>
        <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Root message */}
      <div className="shrink-0 border-b border-slate-100 bg-slate-50 px-4 py-3">
        <div className="flex gap-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
            style={{ backgroundColor: avatarColor(rootMsg.sender_username) }}>
            {rootMsg.sender_username[0]}
          </div>
          <div>
            <div className="mb-0.5 flex items-baseline gap-2">
              <span className="text-xs font-semibold text-slate-700">{rootMsg.sender_username}</span>
              <span className="text-[10px] text-slate-400">{timeStr(rootMsg.created_at)}</span>
            </div>
            <div className="text-sm text-slate-700 rounded-xl bg-white border border-slate-200 px-3 py-2">
              <MarkdownMessage content={rootMsg.content} />
            </div>
          </div>
        </div>
      </div>

      {/* Replies */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {loading && (
          <div className="flex justify-center py-4">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        )}
        {!loading && replies.length === 0 && (
          <p className="text-center text-xs text-slate-400 py-4">No replies yet — be the first!</p>
        )}
        {replies.map(msg => (
          <div key={msg.id} className={`flex gap-2.5 ${isMe(msg) ? "flex-row-reverse" : ""}`}>
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white"
              style={{ backgroundColor: avatarColor(msg.sender_username) }}>
              {msg.sender_username[0]}
            </div>
            <div className={`max-w-[75%] flex flex-col ${isMe(msg) ? "items-end" : "items-start"}`}>
              <div className="mb-0.5 flex items-baseline gap-2">
                <span className="text-[11px] font-semibold text-slate-600">{isMe(msg) ? "You" : msg.sender_username}</span>
                <span className="text-[10px] text-slate-400">{timeStr(msg.created_at)}</span>
              </div>
              <div className={`rounded-xl px-3 py-2 text-sm break-words ${
                isMe(msg) ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-800"
              }`}>
                <MarkdownMessage content={msg.content} inverted={isMe(msg)} />
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Reply input */}
      <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); } }}
            placeholder="Reply in thread…"
            rows={1}
            className="flex-1 resize-none rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
            style={{ maxHeight: 100 }}
            onInput={e => {
              const t = e.currentTarget; t.style.height = "auto";
              t.style.height = `${Math.min(t.scrollHeight, 100)}px`;
            }}
          />
          <button onClick={sendReply} disabled={!input.trim() || sending}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
            {sending ? (
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Message Bubble with hover toolbar ────────────────────────────────────────
function MessageBubble({
  msg,
  showHeader,
  isMe,
  isAdmin,
  channelId,
  currentUserId,
  onEdit,
  onDelete,
  onReact,
  onReplyThread,
  onPin,
}: {
  msg: ChatMessage;
  showHeader: boolean;
  isMe: boolean;
  isAdmin: boolean;
  channelId: string;
  currentUserId: string;
  onEdit: (msg: ChatMessage) => void;
  onDelete: (msg: ChatMessage) => void;
  onReact: (msgId: string, emoji: string) => void;
  onReplyThread: (msg: ChatMessage) => void;
  onPin: (msg: ChatMessage) => void;
}) {
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const color = avatarColor(msg.sender_username);
  const canManage = isMe || isAdmin;
  const canPin = isAdmin;

  const reactions = msg.reactions ?? [];
  const myReactions = new Set(
    reactions.flatMap(r => r.users.includes(currentUserId) ? [r.emoji] : [])
  );

  return (
    <div className={`group flex gap-2.5 ${isMe ? "flex-row-reverse" : ""} ${showHeader ? "mt-3" : "mt-0.5"}`}>
      {/* Avatar */}
      <div className={`w-7 shrink-0 ${showHeader ? "" : "invisible"}`}>
        <div className="relative">
          <div className="flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold text-white uppercase"
            style={{ backgroundColor: color }}>
            {msg.sender_username[0]}
          </div>
        </div>
      </div>

      <div className={`max-w-[75%] sm:max-w-[65%] flex flex-col ${isMe ? "items-end" : "items-start"}`}>
        {/* Name + time header */}
        {showHeader && (
          <div className={`mb-0.5 flex items-baseline gap-2 ${isMe ? "flex-row-reverse" : ""}`}>
            <span className="text-xs font-semibold text-slate-700">{isMe ? "You" : msg.sender_username}</span>
            <span className="text-[10px] text-slate-400">{timeStr(msg.created_at)}</span>
            {msg.pinned && <span className="text-[10px] text-amber-500 font-medium">📌 pinned</span>}
          </div>
        )}

        {/* Bubble — relative wrapper so toolbar can float absolutely beside it */}
        <div className="relative">
          <div className={`rounded-2xl px-3 py-2 text-sm leading-relaxed break-words ${
            isMe
              ? "bg-indigo-600 text-white rounded-tr-sm"
              : "bg-slate-100 text-slate-800 rounded-tl-sm"
          }`}>
            <MessageContent content={msg.content} inverted={isMe} channelId={channelId} />
            {msg.edited_at && (
              <span title={`Edited ${timeStr(msg.edited_at)}`}
                className={`ml-1 text-[10px] italic ${isMe ? "text-indigo-200" : "text-slate-400"}`}>
                (edited)
              </span>
            )}
          </div>

          {/* Floating toolbar — absolute so it never pushes reactions down */}
          <div className={`absolute top-0 ${isMe ? "right-full mr-1.5" : "left-full ml-1.5"}
            flex flex-col gap-0.5
            opacity-0 group-hover:opacity-100 transition-opacity duration-150
            pointer-events-none group-hover:pointer-events-auto z-20`}>

            {/* Quick-react strip */}
            <div className="flex items-center gap-0.5 rounded-2xl border border-slate-200 bg-white shadow-md px-1.5 py-1 whitespace-nowrap">
              {["👍","❤️","😂","😮"].map(qe => (
                <button key={qe} onClick={() => onReact(msg.id, qe)} title={qe}
                  className={`text-lg leading-none rounded-lg p-1 hover:bg-slate-100 active:scale-90 transition-all ${
                    myReactions.has(qe) ? "bg-indigo-50 ring-1 ring-indigo-300" : ""
                  }`}>
                  {qe}
                </button>
              ))}
              <div className="relative">
                <button
                  onClick={() => setShowEmojiPicker(v => !v)}
                  title="More reactions"
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-700 transition-colors text-sm font-semibold">
                  +
                </button>
                {showEmojiPicker && (
                  <EmojiPicker
                    onSelect={emoji => onReact(msg.id, emoji)}
                    onClose={() => setShowEmojiPicker(false)}
                    alignRight={isMe}
                  />
                )}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-0.5 rounded-xl border border-slate-200 bg-white shadow-sm px-0.5 py-0.5 whitespace-nowrap">
              {canManage && (
                <button onClick={() => onEdit(msg)} title="Edit message"
                  className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors text-sm">
                  ✏️
                </button>
              )}
              {canManage && (
                <div className="relative">
                  <button onClick={() => setShowDeleteConfirm(v => !v)} title="Delete message"
                    className="rounded-lg p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-500 transition-colors text-sm">
                    🗑️
                  </button>
                  {showDeleteConfirm && (
                    <div className={`absolute ${isMe ? "right-0" : "left-0"} top-full mt-1 z-50
                      w-44 rounded-xl border border-slate-200 bg-white shadow-lg p-3`}>
                      <p className="text-xs font-medium text-slate-700 mb-2">Delete this message?</p>
                      <div className="flex gap-2">
                        <button onClick={() => { setShowDeleteConfirm(false); onDelete(msg); }}
                          className="flex-1 rounded-lg bg-red-500 py-1.5 text-xs font-medium text-white hover:bg-red-600 transition-colors">
                          Delete
                        </button>
                        <button onClick={() => setShowDeleteConfirm(false)}
                          className="flex-1 rounded-lg border border-slate-200 py-1.5 text-xs text-slate-600 hover:bg-slate-50 transition-colors">
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {canPin && (
                <button onClick={() => onPin(msg)} title={msg.pinned ? "Unpin" : "Pin message"}
                  className={`rounded-lg p-1.5 transition-colors text-sm ${
                    msg.pinned ? "text-amber-500 hover:bg-amber-50" : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                  }`}>
                  📌
                </button>
              )}
              <button onClick={() => onReplyThread(msg)} title="Reply in thread"
                className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors text-sm">
                ↩️
              </button>
            </div>
          </div>
        </div>

        {/* Timestamp for grouped messages */}
        {!showHeader && (
          <span className="mt-0.5 text-[10px] text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity">
            {timeStr(msg.created_at)}
          </span>
        )}

        {/* Reactions */}
        {reactions.length > 0 && (
          <div className={`mt-1 flex flex-wrap gap-1 ${isMe ? "justify-end" : ""}`}>
            {reactions.map(r => (
              <button key={r.emoji} onClick={() => onReact(msg.id, r.emoji)}
                title={`${r.count} reaction${r.count !== 1 ? "s" : ""}`}
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs border transition-colors ${
                  myReactions.has(r.emoji)
                    ? "bg-indigo-100 border-indigo-300 text-indigo-700 font-medium"
                    : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}>
                <span>{r.emoji}</span>
                <span>{r.count}</span>
              </button>
            ))}
          </div>
        )}

        {/* Thread preview */}
        {(msg.thread_count ?? 0) > 0 && (
          <button onClick={() => onReplyThread(msg)}
            className={`mt-1 flex items-center gap-1.5 text-xs text-indigo-500 hover:text-indigo-700 transition-colors ${isMe ? "self-end" : "self-start"}`}>
            <span>↩️</span>
            <span className="font-medium">{msg.thread_count} {msg.thread_count === 1 ? "reply" : "replies"}</span>
            <span className="text-slate-400">· View thread →</span>
          </button>
        )}
      </div>
    </div>
  );
}

// ── Edit Message Inline ───────────────────────────────────────────────────────
function EditMessageForm({
  msg, channelId, isMe, onSave, onCancel,
}: {
  msg: ChatMessage; channelId: string; isMe: boolean;
  onSave: (updated: ChatMessage) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState(msg.content);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);

  async function save() {
    const text = draft.trim();
    if (!text || saving) return;
    setSaving(true);
    try {
      const updated = await api.patch<ChatMessage>(
        `/api/v1/chat/channels/${channelId}/messages/${msg.id}`,
        { content: text }
      );
      onSave({ ...msg, content: updated.content, edited_at: updated.edited_at ?? new Date().toISOString() });
    } catch { /* ignore */ } finally { setSaving(false); }
  }

  return (
    <div className={`flex gap-2.5 mt-0.5 ${isMe ? "flex-row-reverse" : ""}`}>
      <div className="w-7 shrink-0" /> {/* avatar spacer */}
      <div className={`max-w-[75%] sm:max-w-[65%] flex flex-col gap-1.5 ${isMe ? "items-end" : "items-start"}`}>
        <textarea
          ref={ref}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }
            if (e.key === "Escape") onCancel();
          }}
          rows={3}
          className="w-full resize-none rounded-xl border border-indigo-400 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100"
          style={{ minWidth: 240 }}
        />
        <div className="flex gap-2">
          <button onClick={save} disabled={!draft.trim() || saving}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={onCancel}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 transition-colors">
            Cancel
          </button>
        </div>
        <p className="text-[10px] text-slate-400">Enter to save · Escape to cancel</p>
      </div>
    </div>
  );
}

// ── Main ChatPage ─────────────────────────────────────────────────────────────
function ChatPage() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const { getStatus } = usePresence();

  const [user,       setUser]       = useState<User | null>(null);
  const [channel,    setChannel]    = useState<Channel | null>(null);
  const [messages,   setMessages]   = useState<ChatMessage[]>([]);
  const [input,      setInput]      = useState("");
  const [online,     setOnline]     = useState<string[]>([]);
  const [orgUsers,   setOrgUsers]   = useState<OrgUser[]>([]);
  const [dmPartner,  setDmPartner]  = useState<{ id: string; username: string } | null>(null);

  const [showMembers,    setShowMembers]    = useState(false);
  const [chMembers,      setChMembers]      = useState<ChannelMember[]>([]);
  const [addSearch,      setAddSearch]      = useState("");
  const [selectedAddIds, setSelectedAddIds] = useState<string[]>([]);
  const [savingMembers,  setSavingMembers]  = useState(false);

  const [hasMore,        setHasMore]        = useState(false);
  const [loadingMore,    setLoadingMore]    = useState(false);

  const [showRag,    setShowRag]    = useState(false);
  const [ragQuery,   setRagQuery]   = useState("");
  const [ragAnswer,  setRagAnswer]  = useState("");
  const [ragSearching,setRagSearching] = useState(false);

  // Channel-scoped RAG (Ask AI tab)
  const [channelRagQuery,    setChannelRagQuery]    = useState("");
  const [channelRagSearching,setChannelRagSearching] = useState(false);
  const [channelRagHistory,  setChannelRagHistory]  = useState<RagHistoryItem[]>([]);
  const [activeTab,          setActiveTab]          = useState<"messages" | "ask-ai">("messages");

  const [calling,    setCalling]    = useState(false);
  const [callError,  setCallError]  = useState("");

  // Feature 1: editing / reactions
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);

  // Feature 2: thread panel
  const [threadMsg,  setThreadMsg]  = useState<ChatMessage | null>(null);

  // Feature 3: file attachment
  const [attachment,    setAttachment]    = useState<AttachmentChip | null>(null);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Feature 4: emoji autocomplete via `:` trigger
  const [emojiSuggest, setEmojiSuggest] = useState<{ query: string; results: string[] } | null>(null);

  const messagesRef  = useRef<ChatMessage[]>([]);
  messagesRef.current = messages; // Keep ref in sync with render for use in callbacks
  const wsRef        = useRef<WebSocket | null>(null);
  const wsChannelRef = useRef<string | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef    = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLTextAreaElement>(null);
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("disconnected");
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  function handleScroll() {
    const el = scrollAreaRef.current;
    if (!el) return;
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
    if (el.scrollTop < 80 && hasMore && !loadingMore) {
      loadMoreMessages();
    }
  }

  async function loadMoreMessages() {
    if (!channel || loadingMore || !hasMore) return;
    const oldest = messages[0];
    if (!oldest) return;
    setLoadingMore(true);
    const el = scrollAreaRef.current;
    const prevScrollHeight = el?.scrollHeight ?? 0;
    const targetId = channel.id;
    try {
      const older = await api.get<ChatMessage[]>(
        `/api/v1/chat/channels/${targetId}/messages?limit=50&before=${oldest.id}`
      );
      if (wsChannelRef.current !== targetId) return;
      if (older.length < 50) setHasMore(false);
      if (older.length === 0) return;
      setMessages(prev => [...older, ...prev]);
      requestAnimationFrame(() => {
        if (el) el.scrollTop = el.scrollHeight - prevScrollHeight;
      });
    } finally {
      setLoadingMore(false);
    }
  }

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(setUser).catch(() => {});
    api.get<OrgUser[]>("/api/v1/admin/users/search").then(setOrgUsers).catch(() => {});
  }, [router]);

  useEffect(() => {
    const chanId = searchParams.get("channel");
    if (!chanId) return;
    api.get<Channel>(`/api/v1/chat/channels/${chanId}`)
      .then(ch => openChannel(ch))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (channel) setTimeout(() => inputRef.current?.focus(), 50);
  }, [channel]);

  useEffect(() => {
    if (!user || !channel || channel.type !== "dm") return;
    if (dmPartner && dmPartner.id !== user.id) return;
    if (channel.dm_partner_id && channel.dm_partner_username && channel.dm_partner_id !== user.id) {
      setDmPartner({ id: channel.dm_partner_id, username: channel.dm_partner_username });
      return;
    }
    const targetId = channel.id;
    api.get<ChannelMember[]>(`/api/v1/chat/channels/${targetId}/members`).then(members => {
      if (wsChannelRef.current !== targetId) return;
      const partner = members.find(m => m.user_id !== user.id);
      if (partner) setDmPartner({ id: partner.user_id, username: partner.username });
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, channel?.id]);

  function connectWs(channelId: string) {
    if (reconnectRef.current) clearTimeout(reconnectRef.current);
    if (wsRef.current) wsRef.current.close();
    setWsStatus("connecting");
    const token = getAccessToken();
    const ws = new WebSocket(`${getWsBase()}/api/v1/chat/ws/${channelId}?token=${token}`);
    wsRef.current = ws;
    ws.onopen = () => {
      setWsStatus("connected");
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, 30000);
    };
    ws.onmessage = e => {
      const d = JSON.parse(e.data);
      if (d.type === "message") {
        setMessages(prev => prev.some(m => m.id === d.id) ? prev : [...prev, d as ChatMessage]);
        api.post(`/api/v1/chat/channels/${channelId}/read`, {}).catch(() => {});
      }
      if (d.type === "online") setOnline(d.users ?? []);
      if (d.type === "message_updated") {
        setMessages(prev => prev.map(m => m.id === d.id ? { ...m, ...d } : m));
      }
      if (d.type === "message_deleted") {
        setMessages(prev => prev.filter(m => m.id !== d.id));
      }
      if (d.type === "reaction_added" || d.type === "reaction_removed") {
        setMessages(prev => prev.map(m => m.id === d.message_id ? { ...m, reactions: d.reactions ?? [] } : m));
      }
      if (d.type === "thread_reply") {
        // Use authoritative reply_count from server to avoid double-counting
        setMessages(prev => prev.map(m =>
          m.id === d.parent_id ? { ...m, thread_count: d.reply_count ?? (m.thread_count ?? 0) + 1 } : m
        ));
      }
    };
    ws.onerror = () => setWsStatus("disconnected");
    ws.onclose = () => {
      setWsStatus("disconnected");
      if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null; }
      if (wsChannelRef.current === channelId) {
        reconnectRef.current = setTimeout(() => connectWs(channelId), 3000);
      }
    };
  }

  function openChannel(ch: Channel) {
    if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
    if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null; }
    wsChannelRef.current = ch.id;
    setChannel(ch);
    setMessages([]);
    setOnline([]);
    setDmPartner(null);
    setShowRag(false);
    setInput("");
    setHasMore(false);
    setLoadingMore(false);
    setEditingMsgId(null);
    setThreadMsg(null);
    setAttachment(null);
    setActiveTab("messages");
    setChannelRagHistory([]);
    setChannelRagQuery("");

    api.post(`/api/v1/chat/channels/${ch.id}/read`, {}).catch(() => {});

    if (ch.type === "dm") {
      if (ch.dm_partner_id && ch.dm_partner_username) {
        setDmPartner({ id: ch.dm_partner_id, username: ch.dm_partner_username });
      } else {
        const targetId = ch.id;
        api.get<ChannelMember[]>(`/api/v1/chat/channels/${targetId}/members`).then(members => {
          if (wsChannelRef.current !== targetId) return;
          const partner = members.find(m => m.user_id !== (user?.id ?? "__none__")) ?? members[0];
          if (partner) setDmPartner({ id: partner.user_id, username: partner.username });
        }).catch(() => {});
      }
    }

    const targetId = ch.id;
    api.get<ChatMessage[]>(`/api/v1/chat/channels/${targetId}/messages?limit=50`).then(msgs => {
      if (wsChannelRef.current === targetId) {
        setMessages(msgs);
        setHasMore(msgs.length === 50);
      }
    }).catch(() => {});
    connectWs(ch.id);
  }

  // ── File attachment handling ────────────────────────────────────────────────
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) { alert("File too large (max 25 MB)"); return; }
    if (file.type.startsWith("image/")) {
      const reader = new FileReader();
      reader.onload = ev => {
        setAttachment({ file, previewUrl: ev.target?.result as string });
      };
      reader.readAsDataURL(file);
    } else {
      setAttachment({ file });
    }
    // Reset input so the same file can be re-selected
    e.target.value = "";
  }

  async function sendMessage() {
    const text = input.trim();
    if ((!text && !attachment) || !channel) return;

    let content = text;

    // Upload attachment if present
    if (attachment) {
      setUploadingFile(true);
      setUploadProgress(0);
      const isImage = attachment.file.type.startsWith("image/");
      try {
        const form = new FormData();
        form.append("file", attachment.file);
        if (isImage) {
          const res = await api.uploadWithProgress<{ url: string; filename: string }>(
            "/api/v1/chat/media/upload",
            form,
            pct => setUploadProgress(pct),
          );
          content = content ? `${content}\n(img:${res.url})` : `(img:${res.url})`;
        } else {
          form.append("visibility", "channel");
          form.append("channel_id", channel.id);
          const res = await api.uploadWithProgress<{ document_id?: string; id?: string }>(
            "/api/v1/documents/upload",
            form,
            pct => setUploadProgress(pct),
          );
          const docId = res.document_id ?? res.id;
          if (docId) {
            content = content
              ? `${content}\n[📎 ${attachment.file.name}](doc:${docId})`
              : `[📎 ${attachment.file.name}](doc:${docId})`;
          }
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "File upload failed. Please try again.";
        alert(msg);
        setUploadingFile(false);
        setUploadProgress(null);
        return;
      } finally {
        setUploadingFile(false);
        setUploadProgress(null);
        setAttachment(null);
      }
    }

    if (!content.trim()) return;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ content }));
    } else {
      api.post<ChatMessage>(`/api/v1/chat/channels/${channel.id}/messages`, { content })
        .then(msg => setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]))
        .catch(() => {});
    }
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  }

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  // ── Message actions ─────────────────────────────────────────────────────────
  const handleEdit = useCallback((msg: ChatMessage) => {
    setEditingMsgId(msg.id);
  }, []);

  const handleEditSave = useCallback((updated: ChatMessage) => {
    setMessages(prev => prev.map(m => m.id === updated.id ? updated : m));
    setEditingMsgId(null);
  }, []);

  const handleDelete = useCallback(async (msg: ChatMessage) => {
    if (!channel) return;
    try {
      await api.delete(`/api/v1/chat/channels/${channel.id}/messages/${msg.id}`);
      setMessages(prev => prev.filter(m => m.id !== msg.id));
    } catch { /* ignore */ }
  }, [channel]);

  const handleReact = useCallback(async (msgId: string, emoji: string) => {
    if (!channel || !user) return;
    // Determine toggle direction from current state (ref is always current)
    const currentMsg = messagesRef.current.find(m => m.id === msgId);
    const existingReaction = (currentMsg?.reactions ?? []).find(r => r.emoji === emoji);
    const isRemoving = existingReaction?.users.includes(user.id) ?? false;

    // Optimistic update
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      const reactions = m.reactions ?? [];
      const ex = reactions.find(r => r.emoji === emoji);
      if (ex) {
        if (isRemoving) {
          const newUsers = ex.users.filter(id => id !== user.id);
          if (newUsers.length === 0) return { ...m, reactions: reactions.filter(r => r.emoji !== emoji) };
          return { ...m, reactions: reactions.map(r => r.emoji === emoji ? { ...r, users: newUsers, count: newUsers.length } : r) };
        }
        return { ...m, reactions: reactions.map(r => r.emoji === emoji ? { ...r, users: [...r.users, user.id], count: r.count + 1 } : r) };
      }
      return { ...m, reactions: [...reactions, { emoji, count: 1, users: [user.id] }] };
    }));

    try {
      if (isRemoving) {
        await api.delete(`/api/v1/chat/channels/${channel.id}/messages/${msgId}/reactions/${encodeURIComponent(emoji)}`);
      } else {
        await api.post(`/api/v1/chat/channels/${channel.id}/messages/${msgId}/reactions`, { emoji });
      }
      // WS event (reaction_added / reaction_removed) will reconcile with server truth
    } catch { /* ignore */ }
  }, [channel, user]);

  const handlePin = useCallback(async (msg: ChatMessage) => {
    if (!channel) return;
    try {
      if (msg.pinned) {
        await api.delete(`/api/v1/chat/channels/${channel.id}/messages/${msg.id}/pin`);
        setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, pinned: false } : m));
      } else {
        await api.post(`/api/v1/chat/channels/${channel.id}/messages/${msg.id}/pin`, {});
        setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, pinned: true } : m));
      }
    } catch { /* ignore */ }
  }, [channel]);

  const handleReplyThread = useCallback((msg: ChatMessage) => {
    setThreadMsg(msg);
  }, []);

  // WS thread_reply event handles count update authoritatively; this is a no-op fallback
  const handleThreadReply = useCallback((_parentId: string) => { /* WS handles count */ }, []);

  async function startHuddle() {
    if (!channel || calling) return;
    setCalling(true);
    setCallError("");
    try {
      if (channel.type === "dm") {
        const members = await api.get<{ user_id: string; username: string }[]>(
          `/api/v1/chat/channels/${channel.id}/members`
        );
        const other = members.find(m => m.user_id !== user?.id);
        if (!other) { setCalling(false); return; }
        const res = await api.post<{ room_name: string }>("/api/v1/huddle/rooms/direct-call", {
          target_user_id: other.user_id, target_username: other.username,
        });
        router.push(`/huddle/${res.room_name}`);
      } else {
        const res = await api.post<{ room_name: string }>("/api/v1/huddle/rooms/channel-call", {
          channel_id: channel.id,
        });
        router.push(`/huddle/${res.room_name}`);
      }
    } catch (e) {
      setCallError(e instanceof Error ? e.message : "Could not start call");
      setCalling(false);
    }
  }

  async function openMembersDialog() {
    if (!channel) return;
    const [members, users] = await Promise.all([
      api.get<ChannelMember[]>(`/api/v1/chat/channels/${channel.id}/members`),
      api.get<OrgUser[]>("/api/v1/admin/users/search"),
    ]);
    setChMembers(members); setOrgUsers(users);
    setAddSearch(""); setSelectedAddIds([]);
    setShowMembers(true);
  }

  async function handleAddMembers() {
    if (!channel || !selectedAddIds.length) return;
    setSavingMembers(true);
    try {
      await api.post(`/api/v1/chat/channels/${channel.id}/members`, { user_ids: selectedAddIds });
      const members = await api.get<ChannelMember[]>(`/api/v1/chat/channels/${channel.id}/members`);
      setChMembers(members); setSelectedAddIds([]);
    } finally { setSavingMembers(false); }
  }

  async function handleRemoveMember(userId: string) {
    if (!channel) return;
    if (!confirm("Remove this member from the channel?")) return;
    await api.delete(`/api/v1/chat/channels/${channel.id}/members/${userId}`);
    setChMembers(prev => prev.filter(m => m.user_id !== userId));
  }

  async function runRag() {
    if (!ragQuery.trim() || ragSearching) return;
    setRagSearching(true); setRagAnswer("");
    try {
      const conv = await api.post<{ id: string }>("/api/v1/conversations", { title: "Search" });
      const token = getAccessToken();
      const res = await fetch(`/sse/${conv.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ query: ragQuery, top_k: 5 }),
      });
      if (!res.body) return;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n"); buf = parts.pop() ?? "";
        for (const p of parts) {
          const line = p.startsWith("data: ") ? p.slice(6) : p;
          try { const d = JSON.parse(line); if (d.type === "token") setRagAnswer(x => x + d.content); } catch { /* */ }
        }
      }
    } finally { setRagSearching(false); }
  }

  async function runChannelRag() {
    if (!channel || !channelRagQuery.trim() || channelRagSearching) return;
    const q = channelRagQuery.trim();
    setChannelRagSearching(true);
    try {
      const result = await api.post<{ answer: string; sources: { document_id: string; filename: string; chunk_text: string; score: number }[]; query: string }>(
        `/api/v1/chat/channels/${channel.id}/rag`,
        { query: q },
      );
      setChannelRagHistory(prev => [{ query: result.query, answer: result.answer, sources: result.sources }, ...prev]);
      setChannelRagQuery("");
    } catch {
      setChannelRagHistory(prev => [{ query: q, answer: "Sorry, something went wrong. Please try again.", sources: [] }, ...prev]);
    } finally {
      setChannelRagSearching(false);
    }
  }

  const isAdmin = user?.roles?.includes("admin") ?? false;
  const canManageChannel = !!channel && (channel.created_by === user?.id || isAdmin);
  const memberIds = new Set(chMembers.map(m => m.user_id));
  const addable = orgUsers.filter(u =>
    !memberIds.has(u.id) &&
    (u.username.toLowerCase().includes(addSearch.toLowerCase()) ||
     u.email.toLowerCase().includes(addSearch.toLowerCase()))
  );

  function chLabel() {
    if (!channel) return "";
    if (channel.type === "dm") {
      if (dmPartner) return dmPartner.username;
      if (channel.dm_partner_username) return channel.dm_partner_username;
      const parts = channel.name.split(":");
      const otherId = parts.find(p => p !== "dm" && p !== user?.id);
      const other = orgUsers.find(u => u.id === otherId);
      return other?.username ?? "";
    }
    if (channel.type === "group") return `🔒 ${channel.name}`;
    return `# ${channel.name}`;
  }

  // Build message list with date separators
  type RenderedItem =
    | { kind: "sep"; label: string; key: string }
    | { kind: "msg"; msg: ChatMessage; showHeader: boolean };

  const rendered: RenderedItem[] = [];
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const prev = messages[i - 1];
    if (!prev || dateSep(msg.created_at) !== dateSep(prev.created_at)) {
      rendered.push({ kind: "sep", label: dateSep(msg.created_at), key: `sep-${i}` });
    }
    const showHeader = !prev || !sameGroup(prev, msg);
    rendered.push({ kind: "msg", msg, showHeader });
  }

  // (partner presence accessed inline via getStatus())

  return (
    <div className="relative flex flex-1 overflow-hidden bg-white min-w-0">
      {/* Main chat area */}
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {!channel ? (
          <div className="flex flex-1 flex-col items-center justify-center text-slate-400 p-8">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
              className="h-14 w-14 mb-4 text-slate-300">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
            </svg>
            <p className="text-base font-medium text-slate-500">Select a channel or person</p>
            <p className="mt-1 text-sm text-slate-400">Use the sidebar to navigate to a conversation</p>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 border-b border-gray-100 bg-white px-4 py-3 shrink-0">
              {channel.type === "dm" ? (() => {
                const otherName = dmPartner?.username ?? chLabel();
                const isOnline = dmPartner ? online.includes(dmPartner.username) : false;
                // Derive presence dot status from both WS online list and presence hook
                const presenceStatus = dmPartner ? getStatus(dmPartner.id) : "offline";
                const statusDisplay = isOnline ? "online" : presenceStatus !== "offline" ? presenceStatus : "offline";
                return (
                  <div className="flex flex-1 items-center gap-3 min-w-0">
                    <div className="relative shrink-0">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-black text-white text-sm font-bold uppercase">
                        {otherName ? otherName[0] : "?"}
                      </div>
                      <PresenceDot status={statusDisplay} />
                    </div>
                    <div className="min-w-0">
                      <h2 className="text-sm font-semibold text-gray-900 truncate">
                        {otherName || <span className="text-gray-400 font-normal">Loading…</span>}
                      </h2>
                      <p className="flex items-center gap-1 text-xs">
                        {wsStatus === "connecting" ? (
                          <><span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse inline-block" /><span className="text-gray-400">Connecting…</span></>
                        ) : wsStatus === "disconnected" ? (
                          <><span className="h-1.5 w-1.5 rounded-full bg-red-400 inline-block" /><span className="text-red-500">Reconnecting…</span></>
                        ) : statusDisplay === "online" ? (
                          <><span className="h-1.5 w-1.5 rounded-full bg-emerald-500 inline-block" /><span className="text-emerald-600">online</span></>
                        ) : (
                          <><span className="h-1.5 w-1.5 rounded-full bg-gray-300 inline-block" /><span className="text-gray-400">away</span></>
                        )}
                      </p>
                    </div>
                  </div>
                );
              })() : (
                <div className="flex-1 min-w-0">
                  <h2 className="text-sm font-semibold text-gray-900 truncate">{chLabel()}</h2>
                  <p className="text-xs flex items-center gap-1.5">
                    {wsStatus === "connected" ? (
                      <><span className="h-1.5 w-1.5 rounded-full bg-emerald-500 inline-block" /><span className="text-emerald-600">{channel.member_count} members</span></>
                    ) : wsStatus === "connecting" ? (
                      <><span className="h-1.5 w-1.5 rounded-full bg-yellow-400 animate-pulse inline-block" /><span className="text-gray-400">Connecting…</span></>
                    ) : (
                      <><span className="h-1.5 w-1.5 rounded-full bg-red-400 inline-block" /><span className="text-red-500">Reconnecting…</span></>
                    )}
                  </p>
                </div>
              )}
              <div className="flex items-center gap-1.5 shrink-0">
                {/* Tab toggle: Messages | Ask AI (only for non-DM channels) */}
                {channel.type !== "dm" && (
                  <div className="flex rounded-lg border border-slate-200 overflow-hidden text-xs font-medium">
                    <button
                      onClick={() => setActiveTab("messages")}
                      className={`px-2.5 py-1.5 transition-colors ${activeTab === "messages" ? "bg-indigo-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
                      Messages
                    </button>
                    <button
                      onClick={() => setActiveTab("ask-ai")}
                      className={`px-2.5 py-1.5 transition-colors border-l border-slate-200 ${activeTab === "ask-ai" ? "bg-indigo-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
                      Ask AI
                    </button>
                  </div>
                )}
                {channel.type === "dm" && (
                  <button onClick={() => { setShowRag(v => !v); setRagAnswer(""); setRagQuery(""); }}
                    className={`rounded-lg px-2.5 py-1.5 text-xs font-medium border transition-colors ${
                      showRag ? "bg-indigo-50 border-indigo-200 text-indigo-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"
                    }`}>
                    🔍 <span className="hidden sm:inline">Search Docs</span>
                  </button>
                )}
                {channel.type !== "dm" && (
                  <button onClick={openMembersDialog}
                    className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 transition-colors">
                    👥 <span className="hidden sm:inline">{channel.member_count}</span>
                  </button>
                )}
                {/* Call/Huddle button disabled
                {(channel.type === "group" || channel.type === "dm") && (
                  <button onClick={startHuddle} disabled={calling} title="Start video call"
                    className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60 disabled:cursor-wait transition-colors">
                    {calling ? (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3.5 h-3.5 shrink-0 animate-spin">
                        <path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3.5 h-3.5 shrink-0">
                        <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                      </svg>
                    )}
                    <span className="hidden sm:inline">{channel.type === "dm" ? "Call" : "Huddle"}</span>
                  </button>
                )}
                */}
              </div>
            </div>

            {/* Call error banner */}
            {callError && (
              <div className="shrink-0 flex items-center gap-2 border-b border-red-100 bg-red-50 px-4 py-2">
                <span className="text-xs text-red-600 flex-1">{callError}</span>
                <button onClick={() => setCallError("")} className="text-red-400 hover:text-red-600 text-xs">✕</button>
              </div>
            )}

            {/* DM Search Docs RAG panel (legacy) */}
            {showRag && channel.type === "dm" && (
              <div className="shrink-0 border-b border-slate-200 bg-indigo-50 px-4 py-3">
                <div className="flex gap-2 mb-2">
                  <input type="text" value={ragQuery} onChange={e => setRagQuery(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && runRag()}
                    placeholder="Ask about your documents…"
                    className="flex-1 rounded-lg border border-indigo-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400" />
                  <button onClick={runRag} disabled={ragSearching || !ragQuery.trim()}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                    {ragSearching ? "…" : "Ask"}
                  </button>
                </div>
                {ragAnswer && (
                  <div className="rounded-lg border border-indigo-100 bg-white px-3 py-2.5 text-sm text-slate-700 max-h-36 overflow-y-auto">
                    <MarkdownMessage content={ragAnswer} />
                  </div>
                )}
              </div>
            )}

            {/* Ask AI panel (channel-scoped RAG) */}
            {activeTab === "ask-ai" && channel.type !== "dm" && (
              <div className="flex flex-1 flex-col overflow-hidden bg-slate-50">
                {/* Query input */}
                <div className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={channelRagQuery}
                      onChange={e => setChannelRagQuery(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && runChannelRag()}
                      placeholder="Ask anything about documents in this channel…"
                      className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:bg-white transition-colors"
                      disabled={channelRagSearching}
                    />
                    <button
                      onClick={runChannelRag}
                      disabled={channelRagSearching || !channelRagQuery.trim()}
                      className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors min-w-[52px]">
                      {channelRagSearching ? (
                        <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" />
                      ) : "Ask"}
                    </button>
                  </div>
                </div>
                {/* Results history */}
                <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
                  {channelRagHistory.length === 0 && !channelRagSearching && (
                    <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 py-16">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-12 w-12 mb-3 text-slate-300">
                        <circle cx="11" cy="11" r="8" /><path strokeLinecap="round" d="M21 21l-4.35-4.35" />
                      </svg>
                      <p className="font-medium text-slate-500">Ask AI about this channel</p>
                      <p className="text-sm mt-1 max-w-xs">Type a question above to get answers from documents visible to you.</p>
                    </div>
                  )}
                  {channelRagSearching && channelRagHistory.length === 0 && (
                    <div className="flex items-center justify-center py-10 text-slate-400 text-sm gap-2">
                      <span className="inline-block h-4 w-4 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
                      Searching documents…
                    </div>
                  )}
                  {channelRagHistory.map((item, idx) => (
                    <div key={idx} className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                      {/* Question */}
                      <div className="flex items-start gap-2 px-4 py-3 border-b border-slate-100 bg-indigo-50">
                        <span className="mt-0.5 shrink-0 text-indigo-500 font-bold text-xs uppercase tracking-wide">Q</span>
                        <p className="text-sm font-medium text-slate-800">{item.query}</p>
                      </div>
                      {/* Answer */}
                      <div className="px-4 py-3 text-sm text-slate-700">
                        <MarkdownMessage content={item.answer} />
                      </div>
                      {/* Sources */}
                      {item.sources.length > 0 && (
                        <div className="px-4 pb-3 pt-0">
                          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Sources</p>
                          <div className="flex flex-wrap gap-1.5">
                            {item.sources.map((src, si) => (
                              <span key={si} title={src.chunk_text}
                                className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">
                                <svg viewBox="0 0 16 16" fill="currentColor" className="h-2.5 w-2.5 text-slate-400 shrink-0">
                                  <path d="M4 2h6l4 4v8H4V2zm6 0v4h4" />
                                </svg>
                                {src.filename}
                                {src.score != null && <span className="text-slate-400">· {(src.score * 100).toFixed(0)}%</span>}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Messages */}
            {activeTab === "messages" && (
            <div ref={scrollAreaRef} onScroll={handleScroll} className="relative flex-1 overflow-y-auto px-4 pt-4 pb-2 bg-white">
              {loadingMore && (
                <div className="flex justify-center py-2">
                  <span className="text-xs text-slate-400 animate-pulse">Loading older messages…</span>
                </div>
              )}
              {!hasMore && messages.length > 0 && (
                <div className="flex justify-center py-2">
                  <span className="text-xs text-slate-300">— Beginning of conversation —</span>
                </div>
              )}
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-slate-400">
                  <div className="text-4xl mb-2">👋</div>
                  <p className="font-medium text-slate-500">Start the conversation</p>
                  <p className="text-sm mt-1">Say hello to {chLabel()}</p>
                </div>
              )}
              <div className="space-y-0.5">
                {rendered.map((item) => {
                  if (item.kind === "sep") {
                    return (
                      <div key={item.key} className="flex items-center gap-3 py-3">
                        <div className="flex-1 h-px bg-slate-100" />
                        <span className="text-[11px] text-slate-400 font-medium px-2">{item.label}</span>
                        <div className="flex-1 h-px bg-slate-100" />
                      </div>
                    );
                  }
                  const { msg, showHeader } = item;
                  const isMe = msg.sender_id === user?.id;

                  if (editingMsgId === msg.id) {
                    return (
                      <EditMessageForm
                        key={`edit-${msg.id}`}
                        msg={msg}
                        channelId={channel.id}
                        isMe={isMe}
                        onSave={handleEditSave}
                        onCancel={() => setEditingMsgId(null)}
                      />
                    );
                  }

                  return (
                    <MessageBubble
                      key={msg.id}
                      msg={msg}
                      showHeader={showHeader}
                      isMe={isMe}
                      isAdmin={isAdmin}
                      channelId={channel.id}
                      currentUserId={user?.id ?? ""}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                      onReact={handleReact}
                      onReplyThread={handleReplyThread}
                      onPin={handlePin}
                    />
                  );
                })}
              </div>
              <div ref={bottomRef} />
            </div>
            )}

            {showScrollBtn && activeTab === "messages" && (
              <button
                onClick={scrollToBottom}
                className="absolute bottom-16 right-4 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-white shadow-lg ring-1 ring-slate-200 hover:bg-slate-50 transition-all"
                title="Jump to latest">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4 text-slate-600">
                  <path d="M12 5v14M5 12l7 7 7-7" />
                </svg>
              </button>
            )}

            {/* Input — hidden when Ask AI tab is active */}
            {activeTab === "messages" && (
            <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3">
              {/* Emoji autocomplete suggest panel */}
              {emojiSuggest && (
                <div className="mb-2 flex flex-wrap gap-1 rounded-xl border border-slate-200 bg-white shadow-lg p-2">
                  <span className="w-full text-[10px] font-semibold text-slate-400 uppercase tracking-wide px-1 pb-0.5">
                    :{emojiSuggest.query} — click to insert
                  </span>
                  {emojiSuggest.results.map((emoji, i) => (
                    <button
                      key={`${emoji}-${i}`}
                      onMouseDown={e => {
                        e.preventDefault();
                        // Replace :query with the selected emoji
                        const cursor = inputRef.current?.selectionStart ?? input.length;
                        const before = input.slice(0, cursor);
                        const after = input.slice(cursor);
                        const replaced = before.replace(/:([a-z_]{2,20})$/, emoji);
                        setInput(replaced + after);
                        setEmojiSuggest(null);
                        addRecentEmoji(emoji);
                        setTimeout(() => inputRef.current?.focus(), 0);
                      }}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-xl hover:bg-slate-100 transition-colors"
                      title={emoji}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              )}
              {/* Attachment preview — progress shown as circle overlay on the thumbnail */}
              {attachment && (
                <div className="mb-2">
                  <AttachmentChipView
                    chip={attachment}
                    onRemove={() => { if (!uploadingFile) setAttachment(null); }}
                    uploadProgress={uploadingFile ? uploadProgress : null}
                  />
                </div>
              )}
              <div className="flex items-end gap-2">
                {/* File attachment button */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadingFile}
                  title="Attach file"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-700 disabled:opacity-40 transition-colors text-base">
                  📎
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.html,.htm,.pptx,.ppt,.json,.xml"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={e => {
                    const val = e.target.value;
                    setInput(val);
                    // Detect :word pattern at cursor for emoji autocomplete
                    const cursor = e.target.selectionStart ?? val.length;
                    const before = val.slice(0, cursor);
                    const triggerMatch = before.match(/:([a-z_]{2,20})$/);
                    if (triggerMatch) {
                      const results = searchEmojis(triggerMatch[1]).slice(0, 16);
                      setEmojiSuggest(results.length > 0 ? { query: triggerMatch[1], results } : null);
                    } else {
                      setEmojiSuggest(null);
                    }
                  }}
                  onKeyDown={e => {
                    if (emojiSuggest && e.key === "Escape") { setEmojiSuggest(null); return; }
                    handleKey(e);
                  }}
                  placeholder={uploadingFile ? "Uploading file…" : `Message ${chLabel()}…`}
                  disabled={uploadingFile}
                  rows={1}
                  className="flex-1 resize-none rounded-xl border border-slate-300 px-4 py-2.5 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors disabled:opacity-60"
                  style={{ maxHeight: 120 }}
                  onInput={e => {
                    const t = e.currentTarget; t.style.height = "auto";
                    t.style.height = `${Math.min(t.scrollHeight, 120)}px`;
                  }}
                />
                <button
                  onClick={sendMessage}
                  disabled={(!input.trim() && !attachment) || uploadingFile}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors"
                  title="Send (Enter or ⌘↵)">
                  {uploadingFile ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  ) : (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            )}
          </>
        )}

        {/* Members dialog */}
        {showMembers && channel && (
          <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4">
            <div className="w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl bg-white shadow-xl max-h-[85vh] flex flex-col">
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 shrink-0">
                <h3 className="font-semibold text-slate-800">Members — {chLabel()}</h3>
                <button onClick={() => setShowMembers(false)} className="text-slate-400 hover:text-slate-600 text-lg">✕</button>
              </div>
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                {canManageChannel && (
                  <div>
                    <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Add People</p>
                    <input type="search" placeholder="Search by name or email…" value={addSearch}
                      onChange={e => setAddSearch(e.target.value)} autoFocus
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
                    {addSearch.length > 0 && (
                      <div className="mt-1.5 max-h-40 overflow-y-auto rounded-lg border border-slate-200">
                        {addable.length === 0
                          ? <p className="p-3 text-xs text-slate-400">No users found.</p>
                          : addable.map(u => (
                            <label key={u.id} className="flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-slate-50">
                              <input type="checkbox" checked={selectedAddIds.includes(u.id)}
                                onChange={() => setSelectedAddIds(prev => prev.includes(u.id) ? prev.filter(x => x !== u.id) : [...prev, u.id])}
                                className="accent-indigo-600" />
                              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase text-white"
                                style={{ backgroundColor: avatarColor(u.username) }}>{u.username[0]}</div>
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-slate-700">{u.username}</p>
                                <p className="text-xs text-slate-400 truncate">{u.email}</p>
                              </div>
                            </label>
                          ))
                        }
                      </div>
                    )}
                    {selectedAddIds.length > 0 && (
                      <button onClick={handleAddMembers} disabled={savingMembers}
                        className="mt-2 w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                        {savingMembers ? "Adding…" : `Add ${selectedAddIds.length} member${selectedAddIds.length !== 1 ? "s" : ""}`}
                      </button>
                    )}
                  </div>
                )}
                <div className="h-px bg-slate-100" />
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Members ({chMembers.length})</p>
                  <div className="space-y-1.5">
                    {chMembers.map(m => {
                      const mStatus = getStatus(m.user_id);
                      return (
                        <div key={m.user_id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="relative">
                              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase text-white"
                                style={{ backgroundColor: avatarColor(m.username) }}>{m.username[0]}</div>
                              <PresenceDot status={mStatus} />
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-slate-700 truncate">{m.username}</p>
                              <p className="text-xs text-slate-400 truncate">{m.email}</p>
                            </div>
                          </div>
                          {canManageChannel && m.user_id !== user?.id && (
                            <button onClick={() => handleRemoveMember(m.user_id)}
                              className="ml-2 shrink-0 text-xs text-red-400 hover:text-red-600">Remove</button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Thread Panel */}
      {threadMsg && channel && (
        <ThreadPanel
          rootMsg={threadMsg}
          channelId={channel.id}
          currentUserId={user?.id ?? ""}
          onClose={() => setThreadMsg(null)}
          onThreadReply={handleThreadReply}
        />
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense><ChatPage /></Suspense>;
}
