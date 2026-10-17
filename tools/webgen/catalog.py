"""页面上放哪些 demo、官方测试、用户录屏、hydro 测试和标签视频：纯数据清单，不含逻辑。

改页面上的卡片标题 / 说明就改这里；结果数字一律从 NAS 结果文件读（collect.py），不写在这里。
"""

from .config import DEMO_ROOT, OUT_ROOT

# demo 清单：(NAS 目录名, 是否应出视频, 页面标题, 一句话说明)。说明里的 {momentum} 由 run_info.json 的
# run.final_rel_momentum_error 填入。只放 Genesis + lib IPC（2026-10-02 用户：单独 libuipc 的 demo 和扫描不上页面）；
# 官方 Genesis IPC 例子（examples/ipc/；ipc_robot_cloth_teleop 要键盘），相机用官方 viewer 位置。
DEMOS = [
    ("genesis_ipc_objects_falling", True, "布料 + 刚体 + 软球落地（官方例子）",
     "Genesis 官方 examples/ipc/ipc_objects_falling.py，原样；相机 = 官方 viewer 位置。"),
    ("genesis_ipc_momentum", True, "动量守恒检验（官方例子）",
     "官方 ipc_momentum.py：零重力下刚体撞 FEM 球，末步相对动量误差 {momentum}。"),
    ("genesis_ipc_robot_grasp_cube", True, "机械臂抓软方块（官方例子）",
     "官方 ipc_robot_grasp_cube.py：two-way 耦合；Genesis 的刚体在 libuipc 里是 κ = 100 MPa 的 ABD。"),
    ("genesis_ipc_objects_in_box", True, "一堆物体扔进盒子（官方场景 + 我们加的盒子）",
     "Genesis 没有「扔进盒子」的官方例子：这是官方 ipc_objects_falling 场景原样，外加一个开口盒子和更多同款物体。"
     "参数扫描见下方。"),
]

# 用户在自己机器上录的屏（服务器上没有这次运行的 run_info.json）：
# (卡片 key, NAS 上的视频文件, 标题, 说明——服务器上无数据可核的部分用用户原话)
USER_RECORDINGS = [
    ("user_local_ipc_robot_cloth_teleop",
     DEMO_ROOT / "user_local_ipc_robot_cloth_teleop" / "demo.mp4",
     "机械臂遥控抓起一块布（官方例子，用户本地键盘操作录屏）",
     "用户在自己的 Windows 笔记本上运行官方 ipc_robot_cloth_teleop.py（Genesis 1.4.2，带窗口），用键盘遥控录屏，"
     "抓起了一块布（用户告知；这次运行在服务器上没有数据，以视频为准）。按键以代码为准：方向键水平移动，j / k 下 / 上，"
     "空格按住才合夹子；官方文件开头的按键说明与代码不一致。"),
]

# Genesis 自带的 IPC 测试（tests/ipc/），由 run_genesis_ipc_example.py --official-test 在测试自己的 viewer 相机下录像，
# 断言用测试自己的：(NAS 目录名, pytest nodeid, 标题, 检查什么)
OFFICIAL_TESTS = [
    ("genesis_test_test_ground_clearance_0_fit", "tests/ipc/test_rigid.py::test_ground_clearance[0]",
     "离地间隙随接触刚度变（官方测试）",
     "5 个方块落地，contact_resistance 从 1e2 到 1e6；官方断言：不横向漂移、会停住、刚度越大离地间隙越大"
     "（test_rigid.py 257-264 行）。"),
    ("genesis_test_test_ground_sliding_0_fit", "tests/ipc/test_rigid.py::test_ground_sliding[0]",
     "斜向重力下的地面滑动（官方测试）",
     "重力带水平分量，5 个方块摩擦系数 0–0.16；官方断言：不穿地、离地高度与摩擦无关、摩擦越小滑得越远"
     "（test_rigid.py 316-329 行）。"),
    ("genesis_test_test_objects_colliding_0_fit", "tests/ipc/test_rigid.py::test_objects_colliding[0]",
     "布料盖在物体上（官方测试）",
     "物体和布料落地；官方断言：全部落到地面且不穿地、没有飞走、最终静止、布料盖在所有物体上面（test_rigid.py 540-555 行）。"),
    ("genesis_test_test_cloth_corner_drag_0_fit", "tests/ipc/test_deformable.py::test_cloth_corner_drag[0]",
     "夹住布料一角拖动（官方测试）",
     "两个方块夹住布料一角，先静置再拖着画一圈；官方断言：布料没掉、被夹的角始终跟着夹子走（test_deformable.py 253-271 行）。"),
]
# 服务器上查到的某个测试的情况（断言为什么没过，或数据显示了什么；2026-10-02/03，来自 official_test.json 和
# --rigid-trajectory / 诊断重跑），接在卡片的断言结果后面
OFFICIAL_TEST_NOTES = {
    "genesis_test_test_objects_colliding_0_fit": "蓝色的是布料。实测布料开始是平的，"
                                                 "最后高低差 127 mm：中间被方块和球顶起、四周垂下，确实是软布。",
    "genesis_test_test_ground_clearance_0_fit": "期待：接触刚度越大，方块离地越高。实测 5 个方块离地 6.39 / 6.39 / 6.39 / 7.00 / "
                                            "8.18 mm，前 3 个一样，所以没过。原因：libuipc 会把接触刚度夹进按场景算出的区间，"
                                            "前 3 个方块的刚度低于下限，被夹成同一个值（同下方「接触刚度 κ」实验）。",
    "genesis_test_test_ground_sliding_0_fit": "期待：离地高度与摩擦无关。实测 μ = 0.04 的方块比其他的高 9.3 mm：它从第 66 步起"
                                          "往前翻，最后倾斜 16°。原因：libuipc 默认的半隐式提前终止让 Newton 没算到收敛就停，"
                                          "误差积累成翻倒；只关掉它，最大倾角 0.24°，断言通过（把步长减半也能通过，0.31°）。",
}

# Genesis 自带的刚体–刚体 hydroelastic 测试（SAPCoupler，不是 libuipc），由 run_genesis_ipc_example.py
# --official-test --fit-camera 录像（两遍法相机，逐帧检查不出画面）。数字出处见 sandbox docs/drafts/T2.4_web_chapter_plan.md 第 2 节。
HYDRO = {
    "key": "genesis_test_test_sap_rigid_rigid_hydroelastic_contact_64_readable",
    "nodeid": "tests/coupling/test_hybrid.py::test_sap_rigid_rigid_hydroelastic_contact[64]",
    "title": "两条关节链落到盒子上（官方 hydroelastic 测试）",
}
# 其余走压力场接触的 Genesis 官方测试（清单见 sandbox docs/drafts/genesis_hydro_inventory.md；录像命令 run_commands 第 22 条）：
# (目录名, pytest nodeid, 卡片标题, 设置)
HYDRO_MORE = [
    ("genesis_test_test_sap_fem_vs_robot_64_readable", "tests/coupling/test_hybrid.py::test_sap_fem_vs_robot[64]",
     "刚体十字架压软球",
     "Genesis 官方测试 test_sap_fem_vs_robot，原样；FEM 软球半径 0.2 m（E = 1e5 Pa、ν = 0.4）放在地上，自由刚体十字架"
     "（四条带关节的腿）落在球顶；接触对：刚体–软球、软球–地面；dt = 1/60 s、每步 2 个子步、50 步；"
     "官方检查：球心竖直下沉超过 2 cm、十字架停在球顶"),
    ("genesis_test_test_implicit_sap_coupler_collide_sphere_box_64_readable",
     "tests/deformable/test_fem.py::test_implicit_sap_coupler_collide_sphere_box[64]",
     "软方块停在软球顶上",
     "Genesis 官方测试 test_implicit_sap_coupler_collide_sphere_box，原样；FEM 软球半径 0.1 m 放在地上，球顶放一个边长 1.5 cm 的"
     "FEM 软方块（E = 1e4 Pa、密度 50 kg/m³）；接触对：软方块–软球（两个压力场的等压面）、软球–地面；dt = 1/60 s、每步 2 个子步、40 步；"
     "官方检查：两者静止、高度误差 < 5 mm"),
    ("genesis_test_test_franka_panda_grasp_fem_entity_64_sphere_official_cam",
     "tests/integration/test_integration.py::test_franka_panda_grasp_fem_entity[64-sphere]",
     "机械臂夹起软球",
     "Genesis 官方测试 test_franka_panda_grasp_fem_entity（软球那组），原样，相机用测试自带的位置；Franka 机械臂夹起半径 2 cm 的"
     "FEM 软球（E = 1e5 Pa、ν = 0.4）后上提；接触对：手指–软球、软球–地面；dt = 1/60 s，等待 15 步、夹 10 步、上提 65 步、保持 25 步；"
     "官方检查：软球随夹爪上移 5 cm、误差 < 5 mm"),
]

# E0 收敛图：sandbox tools/figs/e0_label_convergence.py 画的，build 时从 NAS outputs/figs/ 复制进 assets/images/
E0_FIG = "e0_label_convergence.png"
# 标签仿真原始输出视频（讲稿里写 [[E0_VIDEO]]、[[E1_VIDEO]]）：sandbox tools/figs/e0_press_video.py 画的，
# 和 demo 视频一起压缩进 assets/videos/；每个压深一帧，左为过球心的竖直截面（竖直方向放大），右为俯视块顶面的竖直位移
LABEL_VIDEOS = {
    "E0": {"key": "e0_press", "video_src": OUT_ROOT / "e0_label_convergence" / "press_video" / "e0_press.mp4",
           "caption": "IPC + FEM 仿真原始输出：半径 1 的刚球压块，压深 0.004–0.024，每个压深停 1.5 s"},
    "E1": {"key": "e1_press_R2", "video_src": OUT_ROOT / "label_validation" / "E1" / "video_R2" / "e1_press_R2.mp4",
           "caption": "IPC + FEM 仿真原始输出：半径 2 的刚球压同一块，压深 0.004–0.013，每个压深停 1.5 s"},
}
# 实验方案 E1–E5 的场景示意图：sandbox tools/figs/experiment_setups.py 用 Genesis 搭场景渲染，每个实验两张
SETUP_ROOT = OUT_ROOT / "experiment_setups"
