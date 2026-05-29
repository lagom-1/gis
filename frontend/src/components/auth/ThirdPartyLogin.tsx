/**
 * 第三方登录按钮组
 * 当前支持微信登录
 */
export default function ThirdPartyLogin() {
  const handleWechatLogin = () => {
    window.location.href = '/api/auth/wechat'
  }

  return (
    <div className="mt-6">
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-stone-200" />
        </div>
        <div className="relative flex justify-center text-xs">
          <span className="bg-white px-3 text-stone-400">或使用以下方式登录</span>
        </div>
      </div>

      <div className="flex justify-center mt-4">
        <button
          onClick={handleWechatLogin}
          className="flex flex-col items-center gap-1.5 group"
          title="微信登录"
        >
          <div className="w-11 h-11 bg-[#07c160] rounded-xl flex items-center justify-center
                          text-white text-sm font-medium group-hover:opacity-90 transition">
            微
          </div>
          <span className="text-[11px] text-stone-400">微信</span>
        </button>
      </div>
    </div>
  )
}
