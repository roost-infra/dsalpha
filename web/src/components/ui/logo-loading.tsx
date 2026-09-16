import React from 'react';

interface LogoLoadingProps {
  size?: number;
  color?: string;
  className?: string;
  style?: React.CSSProperties;
}

function LogoLoading({ size = 60, color = 'currentColor', className = '', style = {} }: LogoLoadingProps) {
  return (
    <div
      className={`logo-loading-wrap ${className}`}
      style={{
        width: size,
        height: size,
        display: 'inline-block',
        ...style
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 60 60"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{
          width: '100%',
          height: '100%',
          filter: 'drop-shadow(0 0 6px var(--color-accent-overlay))',
        }}
      >
        <path
          className="logo-loading-path1"
          d="M11 43.5L23.5 30.5L33 37L49 17.5"
          stroke={color}
          strokeWidth="4.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            strokeDasharray: 56,
            strokeDashoffset: 56,
            animation: 'logo-loading-draw-reverse 4s ease-in-out infinite',
          }}
        />
        <path d="M11 52.5H49" stroke={color} strokeWidth="3.5" strokeLinecap="round" opacity="0.28" />
        <circle cx="49" cy="17.5" r="5.5" fill={color} />
      </svg>

      <style>{`
        @keyframes logo-loading-draw-reverse {
          0%   { stroke-dashoffset: 56; }
          30%  { stroke-dashoffset: 0; }
          55%  { stroke-dashoffset: 0; }
          85%  { stroke-dashoffset: 56; }
          100% { stroke-dashoffset: 56; }
        }
      `}</style>
    </div>
  );
}

export default LogoLoading;
