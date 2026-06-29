# SOTA Template Match Reasoning — sota_3

## Template: MobileNetV2 (轻量化/Inverted Residuals)

**选型依据**：按照 SOTA 轮转策略，第 4 次尝试应选 **MobileNet 轻量化**。

### 已尝试的 SOTA 模板
| Iter | Template | 结果 |
|------|----------|------|
| iter 0 | UNet | PSNR=36.4 (promising) 但 latency=9.99ms 过高 |
| iter 1 | DenseNet | PSNR=22.84 (dead) — 训练发散 |
| iter 2 | ViT | PSNR=22.91 (dead) — 5 epoch 不收敛 |
| **iter 3** | **MobileNetV2 (this)** | — |

### 项目特征分析
1. **输入规格**：`[B, 3, 32, 32]` 图像，值域 [0,1]
2. **输出规格**：`[B, 3, 32, 32]` 重建图像，Sigmoid 输出 [0,1]
3. **当前架构**：encoder-decoder + U-Net skip connection + 残差块 (structural_1)
4. **复杂度约束**：parent 参数量 105K，latency 0.415ms，接近目标 0.404ms
5. **不可替换组件**：Channel 层(AWGN)、power normalization

### 为什么选 MobileNetV2
1. **正值 latency 瓶颈**：parent 的 latency (0.415ms) 已极接近目标 (0.404ms)。MobileNetV2 的 Inverted Residual 结构通过 depthwise convolution 降低计算量，有望进一步压缩 latency。
2. **与 structural_2 的 DSConv 不同**：structural_2 尝试了普通 DSConv 替换所有 conv，但 CPU 上因内存带宽反而更慢。MobileNetV2 使用 expansion→depthwise→projection 三步结构，搭配 residual connection，理论上可避免纯 DSConv 的带宽瓶颈。
3. **保留关键结构**：U-Net skip connection、power norm、Channel 层全部保留。
4. **expansion 因子可控**：使用 expansion=3 而非 6，在轻量化和表征能力间取得平衡。

### 预期 trade-off
- PSNR 可能略低于 parent (MobileNet 的 depthwise conv 表征能力弱于普通 conv)
- latency 有望降至 0.35-0.40ms (接近或达到目标)
- 参数量预计 80-100K (略低于 parent 105K)
