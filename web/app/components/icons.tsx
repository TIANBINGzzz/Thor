import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>;
}

export const PlusIcon = (props: IconProps) => <Icon {...props}><path d="M12 5v14M5 12h14" /></Icon>;
export const ChevronIcon = (props: IconProps) => <Icon {...props}><path d="m8 10 4 4 4-4" /></Icon>;
export const SendIcon = (props: IconProps) => <Icon {...props}><path d="m5 12 14-7-4.5 14-3-5.5L5 12Z" /><path d="m11.5 13.5 3-3" /></Icon>;
export const StopIcon = (props: IconProps) => <Icon {...props}><rect x="7" y="7" width="10" height="10" rx="1" /></Icon>;
export const CopyIcon = (props: IconProps) => <Icon {...props}><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></Icon>;
export const RefreshIcon = (props: IconProps) => <Icon {...props}><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M6.1 9a7 7 0 0 1 11.5-2L20 9M4 15l2.4 2a7 7 0 0 0 11.5-2" /></Icon>;
export const CheckIcon = (props: IconProps) => <Icon {...props}><path d="m5 12 4 4L19 6" /></Icon>;
export const SparkIcon = (props: IconProps) => <Icon {...props}><path d="M12 3c.5 4.4 2.6 6.5 7 7-4.4.5-6.5 2.6-7 7-.5-4.4-2.6-6.5-7-7 4.4-.5 6.5-2.6 7-7Z" /></Icon>;
export const StatsIcon = (props: IconProps) => <Icon {...props}><path d="M5 19V9M12 19V5M19 19v-7" /></Icon>;
export const MenuIcon = (props: IconProps) => <Icon {...props}><line x1="4" y1="6" x2="20" y2="6" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="18" x2="20" y2="18" /></Icon>;
export const SunIcon = (props: IconProps) => <Icon {...props}><circle cx="12" cy="12" r="3.5" /><path d="M12 2.5v2M12 19.5v2M4.58 4.58l1.42 1.42M18 18l1.42 1.42M2.5 12h2M19.5 12h2M4.58 19.42 6 18M18 6l1.42-1.42" /></Icon>;
export const MoonIcon = (props: IconProps) => <Icon {...props}><path d="M20 15.2A7.8 7.8 0 0 1 8.8 4 7.8 7.8 0 1 0 20 15.2Z" /></Icon>;
export const DownloadIcon = (props: IconProps) => <Icon {...props}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></Icon>;
export const ArrowLeftIcon = (props: IconProps) => <Icon {...props}><path d="m15 18-6-6 6-6" /><path d="M9 12h10" /></Icon>;
export const MoreHorizontalIcon = (props: IconProps) => <Icon {...props}><circle cx="5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /></Icon>;
export const PencilIcon = (props: IconProps) => <Icon {...props}><path d="m4 16.5-.8 3.3 3.3-.8L18 7.5a2.1 2.1 0 0 0-3-3L4 16.5Z" /><path d="m13.5 6.5 3 3" /></Icon>;
export const TrashIcon = (props: IconProps) => <Icon {...props}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Icon>;
export const TextModelIcon = (props: IconProps) => <Icon {...props}><path d="M7 6h10M12 6v12M9 18h6" /></Icon>;
export const MultimodalIcon = (props: IconProps) => <Icon {...props}><rect x="4" y="5" width="16" height="14" rx="2" /><circle cx="9" cy="10" r="1.5" /><path d="m6 17 4-4 3 3 2-2 3 3" /></Icon>;
