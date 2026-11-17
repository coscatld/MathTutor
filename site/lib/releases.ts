export const RELEASE_TAG = 'build-20261111-6f84868';
export const RELEASE_URL = `https://github.com/coscatld/MathTutor/releases/tag/${RELEASE_TAG}`;

export type PlatformId = 'windows-x64' | 'macos-arm64';

export type ReleaseAsset = {
  id: PlatformId;
  filename: string;
  url: string;
  os: string;
  arch: string;
  notes: string;
  notesEn: string;
};

export const CURRENT_ASSETS: ReleaseAsset[] = [
  {
    id: 'windows-x64',
    filename: 'MathTutor-windows-x64.exe',
    url: `https://github.com/coscatld/MathTutor/releases/download/${RELEASE_TAG}/MathTutor-windows-x64.exe`,
    os: 'Windows 10/11',
    arch: 'x64',
    notes: 'NSIS 安装包，无 Authenticode 发行证书签名。SmartScreen 可能提示“仍要运行”。',
    notesEn:
      'NSIS installer. Not Authenticode-signed. SmartScreen may ask you to keep the file.',
  },
  {
    id: 'macos-arm64',
    filename: 'MathTutor-mac-arm64.dmg',
    url: `https://github.com/coscatld/MathTutor/releases/download/${RELEASE_TAG}/MathTutor-mac-arm64.dmg`,
    os: 'macOS',
    arch: 'Apple Silicon',
    notes:
      '使用完整本地 ad-hoc 签名，无 Developer ID、未公证。Gatekeeper 默认拒绝，需在“隐私与安全性”中明确允许。',
    notesEn:
      'Fully ad-hoc signed locally, without Developer ID or notarization. Gatekeeper rejects it by default; explicitly allow it under Privacy & Security.',
  },
];

export const LINUX_STATUS = {
  available: false,
  reasonZh:
    '仓库配置了 Linux x64 AppImage 目标。当前尚无经过目标机验收的公开安装包，可按开发文档从源码运行。',
  reasonEn:
    'A Linux x64 AppImage target is configured. A public installer verified on target hardware is not available yet; use the development guide to run from source.',
} as const;
