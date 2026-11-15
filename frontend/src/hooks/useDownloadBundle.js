import { useCallback } from 'react';
import JSZip from 'jszip';
import { message } from 'antd';
import { api } from '../services/api';
import { downloadBlob } from '../utils/download';
import { fetchTranscripts, planFileDownload, planZipDownload } from '../utils/transcriptDownload';

const ZIP_MESSAGE_KEY = 'zipDownload';

/**
 * 轉錄頁與結果頁的「下載單檔結果」與「打包所有已完成檔案」。內容向下載端點拿校正後版本（#346）；
 * 要下載什麼、檔名與拿不到內容時的訊息由 utils/transcriptDownload.js 決定，這裡只觸發下載與顯示訊息。
 */
export function useDownloadBundle(fileList) {
  /** file 是檔案卡上的檔案（name 與 task_uuid），format 是輸出格式。 */
  const downloadFile = useCallback(async (file, format) => {
    const [fetched] = await fetchTranscripts([file], format, api);
    const { download, notice } = planFileDownload(fetched, format);
    if (!download) {
      message.open(notice);
      return;
    }
    downloadBlob(download.content, download.fileName);
  }, []);

  const downloadAllFiles = useCallback(async (format) => {
    const completedFiles = fileList.filter((f) => f.status === 'completed');
    if (completedFiles.length === 0) {
      message.warning('沒有已完成的檔案可以下載！');
      return;
    }

    message.loading({ content: '正在打包檔案...', key: ZIP_MESSAGE_KEY });
    const fetched = await fetchTranscripts(completedFiles, format, api);
    const { entries, zipFileName, notice } = planZipDownload(fetched, format);
    if (entries.length === 0) {
      message.open({ ...notice, key: ZIP_MESSAGE_KEY });
      return;
    }

    try {
      const zip = new JSZip();
      entries.forEach(({ fileName, content }) => zip.file(fileName, content));
      const zipBlob = await zip.generateAsync({ type: 'blob' });
      downloadBlob(zipBlob, zipFileName);
      message.open({ ...notice, key: ZIP_MESSAGE_KEY });
    } catch (error) {
      console.error('打包下載失敗:', error);
      message.error({
        content: '打包下載失敗，請稍後再試',
        key: ZIP_MESSAGE_KEY,
      });
    }
  }, [fileList]);

  return { downloadFile, downloadAllFiles };
}
