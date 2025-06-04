import { theme } from 'antd';

export const customDarkTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#1677ff',
    colorBgLayout: '#141414',
    colorBgContainer: '#1f1f1f',
    colorText: '#FFFFFF',
    colorTextBase: '#FFFFFF',
    colorTextSecondary: 'rgba(255, 255, 255, 0.55)',
    colorTextTertiary: 'rgba(255, 255, 255, 0.40)',
    colorBorder: '#383838',
    colorSplit: '#424242',
  },
  components: {
    Layout: {
      siderBg: '#1f1f1f',
      headerBg: '#1f1f1f',
      bodyBg: '#141414',
    },
    Menu: {
      darkItemBg: '#1f1f1f',
      darkItemSelectedBg: '#2c2c2c',
      darkItemColor: 'rgba(255, 255, 255, 0.90)',
      darkItemHoverColor: '#FFFFFF',
      darkItemSelectedColor: '#FFFFFF',
      darkSubMenuItemBg: '#141414',
    },
    Card: {
      colorBgContainer: '#262626',
      actionsBg: '#262626',
      extraColor: 'rgba(255, 255, 255, 0.75)',
      headColor: '#FFFFFF',
    },
    Button: {
      defaultBg: '#383838',
      defaultColor: '#FFFFFF',
      defaultBorderColor: '#4d4d4d',
      defaultHoverBg: '#4d4d4d',
      defaultHoverColor: '#FFFFFF',
      defaultHoverBorderColor: '#636363',
      colorText: '#FFFFFF',
    },
    Dropdown: {
      colorBgElevated: '#383838',
    },
    Typography: {
      colorText: '#FFFFFF',
      colorTextSecondary: 'rgba(255, 255, 255, 0.55)',
    },
  },
};

export const descriptionParagraphStyle = {
  color: customDarkTheme.token.colorTextSecondary,
  fontSize: '13px',
  marginBottom: '18px',
};

export const optionButtonStyle = {
  background: '#424242',
  borderColor: '#555555',
  color: customDarkTheme.token.colorText,
  padding: '6px 14px',
  fontSize: '14px',
  height: 'auto',
  minWidth: '120px',
  textAlign: 'left',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
};