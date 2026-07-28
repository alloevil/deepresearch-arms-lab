# 执行器环境示例:全部 arm 使用 MiMo 2.5 Pro(或替换成你自己的模型/网关)。
# 用法: cp env_example.sh env.sh,把下面两处占位换成你自己的网关地址和 key,
# 然后 source env.sh。
# 如果你只有官方 Anthropic API,把 ANTHROPIC_BASE_URL 换成
# https://api.anthropic.com、LAB_CLAUDE_BASE_URL 直接删掉即可——arm 代码里
# 这些都是可选的环境变量,缺省会落回标准端点,不需要改代码。
export ANTHROPIC_BASE_URL="https://your-anthropic-compatible-gateway.example"      # core/D/E 拼 /v1，chat+responses 兼容
export ANTHROPIC_AUTH_TOKEN="$YOUR_API_KEY"
export LAB_CLAUDE_BASE_URL="https://your-anthropic-compatible-gateway.example/anthropic"  # arm B 走 Anthropic 协议
export LAB_MODEL_MAIN="xiaomi/mimo-v2.5-pro"
export LAB_MODEL_FAST="xiaomi/mimo-v2.5-pro"
export LAB_AGENT_TIMEOUT=3600     # 推理税重的模型下 B3/F91 常撞 1800s 硬顶(q08_B3 实证)
