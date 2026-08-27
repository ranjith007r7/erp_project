"use client";

import { useState } from "react";
import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { RefreshCw } from "lucide-react";

const REFRESH_THRESHOLD = 70; // px pulled down before release triggers a refresh
const MAX_PULL = 100;

/**
 * A real pull-to-refresh gesture, not a fake spinner shown on a timer.
 * Only activates when dragging DOWN from the very top of the wrapped
 * content (dragConstraints clamps upward movement to 0, so this can
 * never interfere with normal scrolling once content has scrolled
 * past its top).
 *
 * onRefresh should return the real data-reload promise it triggers -
 * the spinner keeps spinning until that promise resolves, not for a
 * fixed fake duration.
 */
export function PullToRefresh({ children, onRefresh }: { children: React.ReactNode; onRefresh: () => Promise<void> }) {
  const y = useMotionValue(0);
  const rotate = useTransform(y, [0, MAX_PULL], [0, 180]);
  const iconOpacity = useTransform(y, [0, 30], [0, 1]);
  const [refreshing, setRefreshing] = useState(false);

  async function handleDragEnd() {
    if (y.get() >= REFRESH_THRESHOLD && !refreshing) {
      setRefreshing(true);
      animate(y, 40, { type: "spring", stiffness: 400, damping: 30 });
      try {
        await onRefresh();
      } finally {
        setRefreshing(false);
        animate(y, 0, { type: "spring", stiffness: 400, damping: 30 });
      }
    } else {
      animate(y, 0, { type: "spring", stiffness: 400, damping: 30 });
    }
  }

  return (
    <div className="relative">
      <motion.div
        className="absolute left-1/2 -translate-x-1/2 -top-2 z-10"
        style={{ opacity: refreshing ? 1 : iconOpacity }}
      >
        <motion.div
          style={{ rotate: refreshing ? undefined : rotate }}
          animate={refreshing ? { rotate: 360 } : undefined}
          transition={refreshing ? { repeat: Infinity, duration: 0.8, ease: "linear" } : undefined}
        >
          <RefreshCw size={20} className="text-slate-400 dark:text-zinc-500" />
        </motion.div>
      </motion.div>
      <motion.div
        drag={refreshing ? false : "y"}
        dragConstraints={{ top: 0, bottom: MAX_PULL }}
        dragElastic={0.3}
        style={{ y }}
        onDragEnd={handleDragEnd}
      >
        {children}
      </motion.div>
    </div>
  );
}
