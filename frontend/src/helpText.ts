export const chartHelp: Record<string, { title: string; body: string }> = {
  synthetic_liquidity: {
    title: '合成流动性（方向）怎么看？',
    body:
      '这是系统用于判定 Regime 的核心信号之一，用公开序列组合来刻画“流动性边际松紧”。\n' +
      '一般解读：\n' +
      '- 🟢：流动性偏改善（更利于 Risk-On）。\n' +
      '- 🟡：中性区间（噪音较大，等待确认）。\n' +
      '- 🔴：流动性偏收紧（更利于 Risk-Off）。\n' +
      '提示：信号灯来自历史分位数阈值，更关注持续性而非单点。'
  },
  credit_spread: {
    title: '信用压力（代理）怎么看？',
    body:
      '信用利差用 HY OAS 等公开序列做代理，是系统的核心风险信号之一。\n' +
      '一般解读：\n' +
      '- 利差走阔/抬升：信用压力上升（偏 Risk-Off）。\n' +
      '- 利差收敛/回落：信用环境改善（偏 Risk-On）。\n' +
      '提示：当信用变差但股市还强，往往是早期预警。'
  },
  funding_stress: {
    title: '资金压力（代理）怎么看？',
    body:
      '资金压力用 SOFR 与 IORB/EFFR 的差值做代理，刻画资金面“紧不紧”。\n' +
      '一般解读：\n' +
      '- 差值扩大：资金压力上升（偏 Risk-Off）。\n' +
      '- 差值收敛：资金压力缓解（偏 Risk-On）。\n' +
      '提示：与信用/VIX 同时转红时，风险信号更可靠。'
  },
  treasury_vol: {
    title: '美债波动（代理）怎么看？',
    body:
      '用 10Y 收益率序列估算实现波动作为利率市场波动代理。\n' +
      '一般解读：\n' +
      '- 波动上升：风险传导更强（偏 Risk-Off）。\n' +
      '- 波动下降：环境更稳定（偏 Risk-On/Neutral）。'
  },
  vix_structure: {
    title: 'VIX 结构（VIX-VXV）怎么看？',
    body:
      'VIX(1M) 与 VXV(3M) 的价差衡量期限结构。\n' +
      '一般解读：\n' +
      '- 价差走高/为正：近端恐慌更强（倒挂倾向，偏 Risk-Off）。\n' +
      '- 价差走低/为负：期限结构健康（升水倾向，偏 Risk-On）。'
  },
  vix_level: {
    title: 'VIX 水平怎么看？',
    body:
      '当缺少 VXV 时，系统会退化使用 VIX 水平分位数做波动压力代理。\n' +
      '一般解读：\n' +
      '- VIX 上行并触及高分位：风险偏好下降（偏 Risk-Off）。\n' +
      '- VIX 回落：风险偏好修复（偏 Risk-On/Neutral）。'
  },
  usd_strength: {
    title: '美元强弱（Fed TWI）怎么看？',
    body:
      '用美联储公布的广义贸易加权美元指数做官方口径的美元强弱代理。\n' +
      '一般解读：\n' +
      '- 美元持续走强：金融条件趋紧（偏 Risk-Off）。\n' +
      '- 美元走弱：外部压力缓和（偏 Risk-On/Neutral）。'
  },
  synthetic_liquidity_delta_w: {
    title: '合成流动性（周变化）怎么看？',
    body:
      '这是一个“流动性松紧”的代理指标（来自公开序列组合的变化）。\n' +
      '一般解读：\n' +
      '- 数值上行/为正：流动性边际改善，偏 Risk-On。\n' +
      '- 数值下行/为负：流动性边际收紧，偏 Risk-Off。\n' +
      '注意：它是 proxy，不等同于单一官方口径；更关注趋势和极端分位。'
  },
  hy_oas: {
    title: '信用压力（HY OAS）怎么看？',
    body:
      '高收益债期权调整利差（OAS），常用作信用风险/融资环境的代理。\n' +
      '一般解读：\n' +
      '- 上行：信用压力上升，偏 Risk-Off。\n' +
      '- 下行：信用环境改善，偏 Risk-On。\n' +
      '提示：看“抬头/加速上行”通常比单日波动更重要。'
  },
  funding_spread: {
    title: '资金压力（SOFR - IORB/EFFR）怎么看？',
    body:
      '用 SOFR 与 IORB/EFFR 的差值做“资金面紧张程度”的代理。\n' +
      '一般解读：\n' +
      '- 差值扩大（更正/更高）：资金压力增大，偏 Risk-Off。\n' +
      '- 差值收敛：资金压力缓解，偏 Risk-On。\n' +
      '提示：与信用/波动一起看，能减少单指标误判。'
  },
  treasury_realized_vol_20d: {
    title: '美债实现波动（20D）怎么看？',
    body:
      '这是对利率市场波动的代理（用 10Y 收益率序列估算 20 日实现波动）。\n' +
      '一般解读：\n' +
      '- 波动上升：跨资产风险传导更强，偏 Risk-Off。\n' +
      '- 波动下降：风险环境更稳定，偏 Risk-On/Neutral。\n' +
      '提示：波动“上台阶”往往比水平本身更危险。'
  },
  vix_slope: {
    title: 'VIX 结构（VIX - VXV）怎么看？',
    body:
      'VIX(1M) 与 VXV(3M) 的价差，刻画期限结构（contango/backwardation）。\n' +
      '一般解读：\n' +
      '- 价差为正/走高：近端恐慌更强（倒挂倾向），偏 Risk-Off。\n' +
      '- 价差为负/走低：期限结构健康（升水倾向），偏 Risk-On。\n' +
      '提示：结构恶化通常比单纯 VIX 水平更早预警。'
  },
  usd_twi_broad: {
    title: '美元强弱（Fed TWI Broad）怎么看？',
    body:
      '这是美联储公布的广义贸易加权美元指数（官方口径）。\n' +
      '一般解读：\n' +
      '- 美元走强（尤其是持续性）：金融条件趋紧，偏 Risk-Off。\n' +
      '- 美元走弱：外部压力缓和，偏 Risk-On/Neutral。\n' +
      '提示：更适合看 1-3 个月趋势，而不是单日噪音。'
  },
  drivers_core: {
    title: '核心 Drivers 怎么解读？',
    body:
      '这里展示用于 Regime 判定的核心信号灯（🟢🟡🔴）。\n' +
      '判定逻辑（简化）：\n' +
      '- 全绿（且核心≥3）→ Regime A（Risk-On）。\n' +
      '- 多红（≥3，或≥2 且 VIX 为红）→ Regime C（Risk-Off）。\n' +
      '- 其它 → Regime B（Neutral）。\n' +
      'risk_score 是“风险压力分”：🟢=0，🟡=1，🔴=2，相加得分；全绿时自然是 0。'
  }
}
