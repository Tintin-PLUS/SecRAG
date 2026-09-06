#!/bin/bash
# 知识库模块启动脚本
# 用法: ./start.sh

echo "========================================="
echo "  证券端侧知识库模块 启动脚本"
echo "========================================="

# 检查Rust环境
if ! command -v cargo &> /dev/null; then
    echo "[ERROR] Rust未安装，请先运行: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

# 检查Python依赖
echo "[1/3] 检查Python依赖..."
if ! python3 -c "import sentence_transformers" &> /dev/null; then
    echo "  安装sentence-transformers..."
    pip3 install sentence-transformers
else
    echo "  [OK] sentence-transformers已安装"
fi

# 编译Rust项目
echo "[2/3] 编译Rust项目..."
cargo build --release 2>&1
if [ $? -ne 0 ]; then
    echo "[ERROR] 编译失败，请检查代码"
    exit 1
fi
echo "  [OK] 编译成功"

# 启动服务
echo "[3/3] 启动知识库服务..."
echo ""
cargo run --release
