"use client";

import { Headphones, Play, Pause } from "lucide-react";
import { useRef, useState } from "react";

interface AudioPlayerProps {
  audioUrl: string;
  title: string;
  concepts?: string[];
}

export function AudioPlayer({ audioUrl, title, concepts }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);

  const togglePlay = () => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setPlaying(!playing);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const isScript = audioUrl.endsWith(".txt");

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 dark:border-indigo-900 dark:bg-indigo-950/20 p-3 my-2">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-500 text-white">
          <Headphones className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{title}</div>
          {concepts && concepts.length > 0 && (
            <div className="text-[10px] text-muted-foreground truncate">
              Covers: {concepts.join(", ")}
            </div>
          )}
        </div>
        {!isScript && (
          <button
            onClick={togglePlay}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-white hover:bg-indigo-600"
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
          </button>
        )}
      </div>

      {!isScript && (
        <>
          {/* Progress bar */}
          <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
            <span>{formatTime(progress)}</span>
            <div
              className="flex-1 h-1 rounded-full bg-indigo-200 dark:bg-indigo-800 cursor-pointer"
              onClick={(e) => {
                if (!audioRef.current || !duration) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const pct = (e.clientX - rect.left) / rect.width;
                audioRef.current.currentTime = pct * duration;
              }}
            >
              <div
                className="h-1 rounded-full bg-indigo-500 transition-all"
                style={{ width: `${duration ? (progress / duration) * 100 : 0}%` }}
              />
            </div>
            <span>{formatTime(duration)}</span>
          </div>
          <audio
            ref={audioRef}
            src={audioUrl}
            onTimeUpdate={() => setProgress(audioRef.current?.currentTime ?? 0)}
            onLoadedMetadata={() => setDuration(audioRef.current?.duration ?? 0)}
            onEnded={() => setPlaying(false)}
          />
        </>
      )}

      {isScript && (
        <div className="mt-2 text-xs text-indigo-600">
          <a href={audioUrl} target="_blank" rel="noopener" className="underline">
            View podcast script
          </a>
          <span className="text-muted-foreground ml-1">(Audio generation requires Fish Audio API key)</span>
        </div>
      )}
    </div>
  );
}
