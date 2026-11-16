import { APP_ICON_REV, APP_ICON_URL, APP_NAME } from '../../../shared/constants.js';

const iconSrc = `${import.meta.env.BASE_URL}${APP_ICON_URL.replace(/^\//, '')}?v=${APP_ICON_REV}`;

/** @param {{ size?: number, className?: string, title?: string }} props */
export default function AppLogo({ size = 32, className = '', title = APP_NAME }) {
  return (
    <img
      src={iconSrc}
      alt={title}
      width={size}
      height={size}
      className={`shrink-0 object-contain ${className}`}
      draggable={false}
    />
  );
}
