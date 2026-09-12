export interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export type InstallPlatform = 'ios' | 'android' | 'other';

export function detectInstallClient(userAgent: string, platform: string, maxTouchPoints: number, coarsePointer: boolean) {
  const ios = /iPad|iPhone|iPod/i.test(userAgent) || (platform === 'MacIntel' && maxTouchPoints > 1);
  const android = /Android/i.test(userAgent);
  return {
    platform: (ios ? 'ios' : android ? 'android' : 'other') as InstallPlatform,
    mobile: ios || android || coarsePointer,
    embedded: /MicroMessenger|\bQQ\/|MQQBrowser|FBAN|FBAV|Instagram|; wv\)/i.test(userAgent),
  };
}

export function installSteps(platform: InstallPlatform, embedded: boolean): string[] {
  if (embedded) return [
    '打开右上角菜单，选择在系统浏览器中打开。',
    platform === 'ios' ? '在 Safari 的分享菜单中选择“添加到主屏幕”。' : '在浏览器菜单中选择“安装应用”或“添加到主屏幕”。',
    '确认添加，即可从主屏幕打开 StudyHub。',
  ];
  if (platform === 'ios') return [
    '点击浏览器的分享按钮。',
    '选择“添加到主屏幕”；若有“作为网页 App 打开”选项，请保持开启。',
    '点击“添加”。若当前浏览器没有此选项，请使用 Safari 打开。',
  ];
  return [
    '打开浏览器菜单。',
    '选择“安装应用”或“添加到主屏幕”，按提示确认。',
    '若没有安装选项，请使用 Chrome 或 Edge 打开本站后重试。',
  ];
}
