"""坐标计算模块 - 将比例坐标转换为实际像素坐标"""

 
class RegionCalculator:
    """根据窗口尺寸将比例坐标转换为像素坐标。"""

    def __init__(self, window_rect: tuple):
        """
        Args:
            window_rect: (left, top, width, height) 屏幕坐标
        """
        self.win_left, self.win_top, self.win_width, self.win_height = window_rect

    def get_pixel_region(self, region_config: dict) -> tuple:
        """
        将比例坐标转换为相对于窗口的像素坐标。
        用于从截图中裁剪区域。

        Returns:
            (x, y, w, h) 相对于窗口左上角
        """
        x = int(region_config["x_ratio"] * self.win_width)
        y = int(region_config["y_ratio"] * self.win_height)
        w = int(region_config["w_ratio"] * self.win_width)
        h = int(region_config["h_ratio"] * self.win_height)
        return (x, y, w, h)

    def get_screen_region(self, region_config: dict) -> tuple:
        """
        将比例坐标转换为屏幕绝对坐标。
        用于点击操作。

        Returns:
            (x, y, w, h) 屏幕坐标
        """
        x = self.win_left + int(region_config["x_ratio"] * self.win_width)
        y = self.win_top + int(region_config["y_ratio"] * self.win_height)
        w = int(region_config["w_ratio"] * self.win_width)
        h = int(region_config["h_ratio"] * self.win_height)
        return (x, y, w, h)

    def get_click_point(self, region_config: dict) -> tuple:
        """
        返回区域中心点的屏幕坐标。
        这是鼠标点击的目标位置。

        Returns:
            (screen_x, screen_y)
        """
        x, y, w, h = self.get_screen_region(region_config)
        return (x + w // 2, y + h // 2)
