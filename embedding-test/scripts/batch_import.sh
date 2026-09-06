#!/bin/bash
# 批量导入脚本：遍历指定文件夹，导入所有支持的文档
# 用法: bash scripts/batch_import.sh /path/to/docs bge-small

DOCS_DIR="${1:-test_docs}"
MODEL="${2:-bge-small}"
API="http://127.0.0.1:8901/api/ingest"

echo "=========================================="
echo "  批量导入文档"
echo "  文件夹: $DOCS_DIR"
echo "  模型:   $MODEL"
echo "=========================================="
echo ""

success=0
fail=0

for file in "$DOCS_DIR"/*.md "$DOCS_DIR"/*.txt "$DOCS_DIR"/*.pdf; do
    # 如果文件不存在（通配符没匹配到），跳过
    [ ! -f "$file" ] && continue

    filename=$(basename "$file")
    echo -n "  导入: $filename ... "

    response=$(curl --noproxy '*' -s -X POST "$API" \
        -H "Content-Type: application/json" \
        -d "{\"file_path\": \"$file\", \"model\": \"$MODEL\"}")

    status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)

    if [ "$status" = "success" ]; then
        chunks=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('chunk_count',0))" 2>/dev/null)
        echo "OK ($chunks 块)"
        success=$((success + 1))
    else
        echo "FAIL"
        echo "    $response"
        fail=$((fail + 1))
    fi
done

echo ""
echo "=========================================="
echo "  完成: 成功 $success 份, 失败 $fail 份"
echo "=========================================="
