# UniMatch

UniMatch hỗ trợ phân công sinh viên với giảng viên hướng dẫn theo độ phù hợp chuyên môn và quota. Portal dùng FastAPI và frontend tĩnh. Pipeline nghiên cứu đánh giá RL hai cấp với các baseline phân công trên cùng dữ liệu và ràng buộc.

- [Yêu cầu sản phẩm](PRD.md)
- [Đặc tả kỹ thuật](SPEC.md)
- [Chỉ mục tài liệu](DOCS.md)

## Kiểm tra cục bộ

```powershell
python -m pip install -r requirements-rebuild-web.txt
node frontend/build.mjs
python -m pytest -q
```

Xem [hướng dẫn portal](docs/portal_setup.md) và [hướng dẫn RL hai cấp](docs/rl_2_cap_training_guide.md) để chuẩn bị dữ liệu và artifact trước khi chạy.
