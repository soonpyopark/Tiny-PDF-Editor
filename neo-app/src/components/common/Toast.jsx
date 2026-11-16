import { useEffect } from 'react';

/**
 * 토스트 알림 (우측 상단).
 * @param {{ message: string, type?: 'info' | 'success' | 'error' | 'warning', onClose?: () => void, autoClose?: number }} props
 */
export default function Toast({ message, type = 'info', onClose, autoClose = 5000 }) {
  useEffect(() => {
    if (!autoClose || !onClose) return;
    const timer = setTimeout(onClose, autoClose);
    return () => clearTimeout(timer);
  }, [autoClose, onClose]);

  const bgColor = {
    info: 'bg-blue-50 text-blue-800 border-blue-200',
    success: 'bg-green-50 text-green-800 border-green-200',
    error: 'bg-red-50 text-red-800 border-red-200',
    warning: 'bg-yellow-50 text-yellow-800 border-yellow-200',
  }[type];

  const iconColor = {
    info: 'text-blue-400',
    success: 'text-green-400',
    error: 'text-red-400',
    warning: 'text-yellow-400',
  }[type];

  return (
    <div className={`fixed bottom-4 right-4 max-w-sm rounded-lg border p-4 ${bgColor} shadow-lg animate-slideInUp`}>
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 h-5 w-5 shrink-0 rounded-full ${iconColor}`}>
          {type === 'error' && '✕'}
          {type === 'success' && '✓'}
          {type === 'warning' && '⚠'}
          {type === 'info' && 'ⓘ'}
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium">{message}</p>
        </div>
        {onClose && (
          <button
            className="ml-2 text-current opacity-50 hover:opacity-100 transition-opacity"
            onClick={onClose}
            aria-label="닫기"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
