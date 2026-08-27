"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ============================================================================
// Web Speech API 类型声明
// ----------------------------------------------------------------------------
// TypeScript 5.9 的 lib.dom.d.ts 只内置了 SpeechRecognitionAlternative /
// SpeechRecognitionResult / SpeechRecognitionResultList，缺少 Recognition
// 实例本身及其事件类型。这里在全局补充缺失部分（与 lib.dom 现有声明合并），
// 全程不使用 any 绕过类型检查。
// ============================================================================

declare global {
  interface SpeechRecognitionEvent extends Event {
    resultIndex: number;
    results: SpeechRecognitionResultList;
  }

  interface SpeechRecognitionErrorEvent extends Event {
    error: string;
    message?: string;
  }

  interface SpeechRecognition extends EventTarget {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    maxAlternatives: number;
    start(): void;
    stop(): void;
    abort(): void;
    onstart: ((this: SpeechRecognition, ev: Event) => void) | null;
    onresult: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => void) | null;
    onerror: ((this: SpeechRecognition, ev: SpeechRecognitionErrorEvent) => void) | null;
    onend: ((this: SpeechRecognition, ev: Event) => void) | null;
  }

  interface SpeechRecognitionConstructor {
    new (): SpeechRecognition;
    prototype: SpeechRecognition;
  }

  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}

// ============================================================================
// 用户友好的中文错误信息
// ============================================================================

export type SpeechErrorCode =
  | "not-allowed"
  | "no-speech"
  | "audio-capture"
  | "network"
  | "aborted"
  | "service-not-allowed"
  | "unsupported"
  | "unknown";

export interface SpeechErrorInfo {
  code: SpeechErrorCode;
  /** 面向用户的友好中文提示，绝不暴露原始异常。 */
  message: string;
}

const ERROR_MESSAGES: Record<SpeechErrorCode, string> = {
  "not-allowed": "请允许 Chrome 使用麦克风后重试",
  "no-speech": "没有听清，请再试一次",
  "audio-capture": "未检测到可用麦克风，请检查设备后重试",
  network: "语音识别网络异常，请检查网络后重试",
  aborted: "录音已中止，请重试",
  "service-not-allowed": "语音识别服务暂不可用，请稍后重试",
  unsupported: "当前浏览器暂不支持语音输入",
  unknown: "语音识别失败，请重试",
};

function mapError(rawError: string): SpeechErrorInfo {
  switch (rawError) {
    case "not-allowed":
    case "service-not-allowed":
      return { code: "not-allowed", message: ERROR_MESSAGES["not-allowed"] };
    case "no-speech":
      return { code: "no-speech", message: ERROR_MESSAGES["no-speech"] };
    case "audio-capture":
      return { code: "audio-capture", message: ERROR_MESSAGES["audio-capture"] };
    case "network":
      return { code: "network", message: ERROR_MESSAGES.network };
    case "aborted":
      return { code: "aborted", message: ERROR_MESSAGES.aborted };
    default:
      return { code: "unknown", message: ERROR_MESSAGES.unknown };
  }
}

/**
 * 浏览器语音识别 Hook（基于 Web Speech API）。
 *
 * - 运行时检测 `window.SpeechRecognition` / `window.webkitSpeechRecognition`，
 *   不使用 userAgent 判断支持情况。
 * - 识别配置固定为 zh-CN / interimResults=true / continuous=false。
 * - 每次开始录音都会重建实例并绑定一次监听器；停止时清理监听与实例，
 *   组件卸载时强制中止，避免重复 listener / 泄漏。
 * - `transcript` 为已确认（final）结果累积值，`interimTranscript` 为临时
 *   结果，两者均只供 UI 展示，组件必须手动发送，本 Hook 绝不自动提交。
 */
export function useSpeechInput() {
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef = useRef("");

  const [isSupported, setIsSupported] = useState(
    () =>
      typeof window !== "undefined" &&
      Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  );
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<SpeechErrorInfo | null>(null);

  // 运行时检测（与 useState 初始化一致，保留以便测试/热重载兜底）。
  useEffect(() => {
    if (typeof window === "undefined") return;
    setIsSupported(Boolean(window.SpeechRecognition || window.webkitSpeechRecognition));
  }, []);

  const createRecognition = useCallback((): SpeechRecognition | null => {
    if (typeof window === "undefined") return null;
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Ctor) return null;
    const rec = new Ctor();
    rec.lang = "zh-CN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    return rec;
  }, []);

  /** 解绑全部监听并中止当前实例，供重新录音与卸载时复用。 */
  const teardown = useCallback(() => {
    const rec = recognitionRef.current;
    if (!rec) return;
    rec.onstart = null;
    rec.onresult = null;
    rec.onerror = null;
    rec.onend = null;
    try {
      rec.abort();
    } catch {
      // 实例已停止，忽略。
    }
    recognitionRef.current = null;
  }, []);

  const startListening = useCallback(() => {
    // 重新录音前先彻底清理上一次实例，避免残留监听器与 transcript。
    teardown();
    finalTranscriptRef.current = "";
    setInterimTranscript("");
    setTranscript("");
    setError(null);

    const rec = createRecognition();
    if (!rec) {
      setError({ code: "unsupported", message: ERROR_MESSAGES.unsupported });
      return;
    }

    rec.onstart = () => setIsListening(true);

    rec.onresult = (ev) => {
      let finalText = "";
      let interimText = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const result = ev.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalText += text;
        } else {
          interimText += text;
        }
      }
      if (finalText) {
        finalTranscriptRef.current += finalText;
      }
      setTranscript(finalTranscriptRef.current + interimText);
      setInterimTranscript(interimText);
    };

    rec.onerror = (ev) => {
      // 只暴露映射后的友好文案，不向 UI 传递原始 error code/exception。
      setError(mapError(ev.error));
    };

    rec.onend = () => {
      setIsListening(false);
      setInterimTranscript("");
      recognitionRef.current = null;
    };

    recognitionRef.current = rec;
    try {
      rec.start();
    } catch {
      setError({ code: "unknown", message: ERROR_MESSAGES.unknown });
    }
  }, [createRecognition, teardown]);

  const stopListening = useCallback(() => {
    const rec = recognitionRef.current;
    if (!rec) return;
    try {
      rec.stop();
    } catch {
      // 尚未开始，忽略。
    }
  }, []);

  // 组件卸载时停止并清理识别实例。
  useEffect(() => teardown, [teardown]);

  return {
    isSupported,
    isListening,
    interimTranscript,
    transcript,
    error,
    startListening,
    stopListening,
  };
}
