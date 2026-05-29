type LoginTab = 'password' | 'code'

interface TabSwitcherProps {
  activeTab: LoginTab
  onTabChange: (tab: LoginTab) => void
}

/**
 * 登录方式切换标签
 * 支持密码登录和验证码登录两种模式
 */
export default function TabSwitcher({ activeTab, onTabChange }: TabSwitcherProps) {
  const tabs: { key: LoginTab; label: string }[] = [
    { key: 'password', label: '密码登录' },
    { key: 'code', label: '验证码登录' },
  ]

  return (
    <div className="flex gap-2 mb-6">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === tab.key
              ? 'bg-emerald-600 text-white'
              : 'bg-stone-100 text-stone-500 hover:text-stone-700'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
