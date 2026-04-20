# Bài thuyết trình: Hiện thực chế độ Online cho dự án Connect Four (2–3 người)

Chào mọi người. Trong phần này tôi sẽ trình bày toàn bộ tiến trình tôi đã làm để đưa chế độ **Online** vào dự án board game này: dùng công nghệ gì, các bước chạy ra sao, và luồng dữ liệu từ lúc mở game đến lúc đánh một nước trên mạng.

---

## 1. Mục tiêu của chế độ Online

Ở đây, mục tiêu của tôi là cho phép nhiều người chơi ở **các máy khác nhau** cùng vào một phòng, chờ trong lobby, rồi chơi ván bài với **trạng thái trận đấu thống nhất** — tức là không ai “tự sửa bàn cờ” ở phía client. Vì vậy tôi thiết kế theo hướng **server là nguồn sự thật (authoritative server)**: mọi nước đi hợp lệ đều do server xác nhận và phát lại cho tất cả người trong phòng.

---

## 2. Tôi chọn Socket.IO để làm gì?

Ở đây, tôi sử dụng **Socket.IO** (cụ thể là `python-socketio`) để làm lớp **giao tiếp hai chiều thời gian thực** giữa client game (Pygame) và server.

Lý do tôi chọn nó:

- Game cần **sự kiện** liên tục: vào phòng, cập nhật lobby, bắt đầu trận, cập nhật bàn cờ, thông báo lượt, kết thúc trận — kiểu “bắn sự kiện” qua WebSocket rất hợp.
- Socket.IO đã quen thuộc với mô hình **emit / on**, dễ map một-một với các hành động trong game.
- Phía client tôi dùng **`python-socketio[client]`** để tạo `socketio.Client`; phía server tôi dùng **`python-socketio`** với **`async_mode="asgi"`** để gắn vào FastAPI.

Tóm lại: Socket.IO là “đường ống” để client và server nói chuyện với nhau theo tên sự kiện, không phải tôi tự viết giao thức TCP thô.

---

## 3. Phía server: FastAPI + Socket.IO

Ở bước tiếp theo, tôi dựng một **server ASGI** nhỏ.

- Tôi dùng **FastAPI** để có vài endpoint HTTP tiện kiểm tra và thống kê.
- Trong `server/main.py`, tôi tạo `socketio.AsyncServer`, bọc bằng `socketio.ASGIApp` thành `socket_app`, rồi chạy bằng **Uvicorn** với lệnh dạng: `uvicorn server.main:socket_app --host 0.0.0.0 --port 8000`.

Ý nghĩa của việc bind `0.0.0.0` là server lắng nghe trên mọi giao diện mạng của máy — sau này khi tôi dùng tunnel (ví dụ ngrok) thì traffic từ bên ngoài mới vào được cổng đó.

Tôi cũng bật **CORS** cho FastAPI và cấu hình `cors_allowed_origins` cho Socket.IO để trình duyệt hoặc client không bị chặn khi kết nối chéo nguồn (tùy môi trường).

Ngoài Socket.IO, server còn có:

- `GET /healthz` — kiểm tra sống/chết.
- `GET /` — trả JSON thống kê kiểu service name, số phòng đang hoạt động, số game đang chạy (tiện demo và debug).

---

## 4. Giao thức chung: thư mục `shared/`

Ở đây, tôi không muốn client và server mỗi bên tự đặt tên chuỗi sự kiện khác nhau. Vì vậy tôi tạo file **`shared/protocol.py`**.

Trong đó tôi định nghĩa:

- **Tên sự kiện** từ client gửi lên server: ví dụ `create_room`, `join_room`, `start_game`, `make_move`, `chat_message`, v.v.
- **Tên sự kiện** server gửi xuống client: ví dụ `room_updated`, `game_started`, `game_update`, `your_turn`, `game_over`, `error`, v.v.
- **Mã lỗi** thống nhất: `ROOM_NOT_FOUND`, `ROOM_FULL`, `NOT_YOUR_TURN`, `INVALID_MOVE`, …
- Các **DTO** (data transfer object) mô tả cấu trúc phòng, người chơi, slot AI, và snapshot trạng thái game để gửi qua mạng.

Cách làm này giúp khi tôi sửa một bên, bên kia vẫn “khớp” tên và payload.

---

## 5. Logic phòng và người chơi: `RoomManager`

Ở bước tiếp theo, tôi cần một lớp quản lý phòng trong bộ nhớ.

Trong `server/room_manager.py`, class **`RoomManager`** làm các việc:

- Tạo phòng với **mã 6 ký tự** (random từ bảng chữ cái số theo cấu hình).
- Ghi nhớ **socket id** (sid) của từng người đang ở phòng nào — vì Socket.IO dùng sid để biết ai là ai.
- Cho phép **host** kick, thêm/xóa AI ở slot trống, v.v.
- Phục vụ danh sách phòng **public** để màn hình “Browse Rooms” hiển thị.

Khi người chơi **disconnect**, server cập nhật phòng, thông báo người còn lại, và dọn dẹp nếu cần — phần này nằm trong các handler Socket.IO ở `server/events.py`.

---

## 6. Ván đấu “đúng luật” trên server: `GameSession`

Điểm quan trọng: **logic bàn cờ không chỉ chạy trên máy người chơi**. Ở đây, tôi tái sử dụng luôn **`board.py`** và **`ai.py`** phía server trong `server/game_session.py`.

Class **`GameSession`**:

- Khởi tạo bàn cờ, điểm, lượt hiện tại theo cấu hình phòng (2 hoặc 3 người, có cả slot AI).
- **Xác thực nước đi** khi nhận `make_move` — chỉ chấp nhận đúng người đúng lượt.
- Khi tới lượt AI, server **tự tính nước** (Random / MCTS / Minimax giống offline), có thể thêm độ trễ nhỏ để UX dễ theo dõi.
- Sau mỗi thay đổi hợp lệ, server tạo **snapshot** trạng thái game và phát `game_update` cho cả phòng.

Như vậy, dù client có bị “gian lận” gửy cột sai, server vẫn là người quyết định cuối cùng.

---

## 7. Các handler sự kiện: `server/events.py`

Ở đây, tôi gom toàn bộ **client → server** vào các hàm `on_*` đăng ký với Socket.IO, ví dụ:

- `create_room` — gắn sid làm host, tạo mã phòng, đưa sid vào “room” Socket.IO theo mã phòng.
- `join_room` — người mới vào, broadcast `room_updated`, thông báo `player_joined` cho người khác.
- `start_game` — **chỉ host** được gọi; kiểm tra đủ chỗ; khởi tạo `GameSession`; phát `game_started`; nếu lượt đầu là AI thì chạy luồng AI; nếu là người thì gửi `your_turn` đúng sid.
- `make_move` — validate session, validate lượt, cập nhật state, rồi hoặc tiếp tục AI, hoặc chuyển lượt người tiếp theo bằng `your_turn`, hoặc `game_over`.

Nói ngắn gọn: file này là “bộ não điều phối” của online mode.

---

## 8. Phía client Pygame: mạng lưới và giao diện

### 8.1. `client/network.py` — bọc Socket.IO client

Ở đây, tôi viết class **`NetworkManager`** để:

- Gọi `socketio.Client.connect(server_url, …)` với transport websocket/polling.
- Đăng ký listener cho từng sự kiện server (map sang callback nội bộ).
- Cung cấp các hàm tiện như `create_room`, `join_room`, `make_move`, … bên trong chỉ là `emit` đúng tên sự kiện trong `shared/protocol.py`.

### 8.2. `client/online_manager.py` — cầu nối thread-safe

Socket.IO client chạy trên **thread nền**, còn Pygame vẽ màn hình trên **thread chính**. Vì vậy tôi cần một lớp **`OnlineManager`**:

- Nhận callback từ mạng, ghi vào hàng đợi sự kiện; mỗi frame game loop gọi `drain_events()` để đưa về thread chính xử lý an toàn.
- Lưu trạng thái: phòng hiện tại, snapshot game, sid của tôi, slot của tôi, có phải host không, có phải lượt của tôi không.
- Cung cấp `am_host()`, `make_move(col)` — trong đó `make_move` chỉ gửi lên server khi đúng lượt.

### 8.3. `online_ui.py` — mixin giao diện Online

Ở đây, tôi không tách app thành hai codebase; tôi dùng **mixin** gắn vào class `App` chính trong `app.py`:

- Các state như `online_menu`, `room_lobby`, `playing_online`, …
- Vẽ form nhập **tên hiển thị**, ô **Server URL**, nút tạo phòng / join code / duyệt phòng public.
- Khi nhận sự kiện từ `OnlineManager`, chuyển màn hình tương ứng (vào lobby, vào bàn, game over, …).

Như vậy, người chơi chỉ cần chạy `python main.py` như bình thường, chọn chế độ Online là vào được luồng này.

---

## 9. Bước vận hành thực tế: server, client, và ngrok

### 9.1. Cần cài những gì?

- **Máy chạy server**: vào thư mục `server/`, cài `pip install -r requirements.txt` (FastAPI, uvicorn, python-socketio, v.v.).
- **Máy chạy game (client)**: ở root project, cài `pip install -r requirements.txt` — trong đó có **Pygame** và **`python-socketio[client]`**.

Hai môi trường tách dependency để server không bắt buộc phải cài Pygame trên máy chỉ chạy backend.

### 9.2. Chạy server

Tôi chạy server bằng Uvicorn trỏ vào `socket_app` như đã nói. Khi server lên, tôi có thể mở trình duyệt hoặc `curl` vào `GET /` để thấy JSON dạng `service`, `rooms_active`, `games_active` — đây là cách tôi kiểm tra nhanh server có sống không.

### 9.3. Tôi dùng ngrok để làm gì?

Ở bước tiếp theo, khi tôi muốn **hai máy khác mạng** (hoặc bạn bè không cùng LAN) cùng chơi mà **không mở port trên router**, tôi dùng **ngrok**.

Cách làm:

1. Tôi chạy server local trên một cổng cố định (ví dụ **8000**).
2. Tôi chạy lệnh dạng `ngrok http 8000` (hoặc đúng cổng server đang listen).
3. Ngrok cấp cho tôi một URL HTTPS công khai, ví dụ dạng `https://....ngrok-free.dev`.
4. Trên **mọi máy client**, tôi mở game → **Online** → điền **Server URL** đúng URL đó (không thêm path thừa phía sau).

Lưu ý tôi thường nhắc trong demo: URL miễn phí của ngrok **đổi** mỗi lần tôi restart ngrok, và tôi phải giữ **cả server lẫn ngrok** chạy suốt phiên chơi.

### 9.4. Cấu hình mặc định URL trên client

Trong quá trình triển khai, tôi còn đặt sẵn **`DEFAULT_SERVER_URL`** trong `constants.py` trỏ tới URL ngrok đang dùng (ví dụ `https://rectify-equate-jeep.ngrok-free.dev`), để người mở game lần đầu không phải gõ tay nếu đang demo cùng một tunnel. Khi đổi tunnel hoặc deploy server thật, tôi chỉ cần sửa lại hằng số này hoặc nhập trực tiếp trên màn hình Online.

---

## 10. Luồng hoạt động end-to-end (tóm tắt có thứ tự)

Để mọi người hình dung trọn vẹn, tôi tóm lại một lần:

1. Server chạy — Socket.IO lắng nghe trên cùng process với FastAPI.
2. Client mở game, nhập URL server, bấm kết nối — `NetworkManager` thiết lập phiên Socket.IO.
3. Host tạo phòng — server tạo mã, gắn host_id là sid của host, trả `room_created`.
4. Bạn bè join bằng code hoặc từ danh sách phòng public — server cập nhật phòng và broadcast `room_updated`.
5. Host chỉnh AI nếu cần, đủ người thì **Start** — server tạo `GameSession`, phát `game_started` và trạng thái ban đầu.
6. Đến lượt ai — client chỉ gửi `make_move` khi nhận `your_turn`; server kiểm tra và phát `game_update` cho mọi người.
7. Hết trận — server phát `game_over`; có thể host xin **rematch** theo logic server đã định.

---

## 11. Kết luận

Tóm lại, phần Online của dự án này là sự kết hợp giữa:

- **Socket.IO** cho kênh realtime,
- **FastAPI + Uvicorn** cho ASGI và HTTP phụ trợ,
- **Giao thức thống nhất** trong `shared/protocol.py`,
- **Server authoritative** với `RoomManager` + `GameSession` (tái dùng `board.py` / `ai.py`),
- Và **client Pygame** tách lớp mạng (`client/`) + mixin UI (`online_ui.py`),

cùng **ngrok** (hoặc host thật) khi cần chơi qua Internet.

Cảm ơn mọi người đã lắng nghe. Nếu có câu hỏi về một sự kiện cụ thể hoặc chỗ xử lý lượt AI trên server, tôi sẵn sàng đi sâu thêm.
