"use client";

import { useState } from "react";
import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { Trash2 } from "lucide-react";

const DELETE_THRESHOLD = -80; // px dragged left before a release commits to delete
const MAX_DRAG = -120; // px - how far left the item can actually travel

/**
 * Wraps a single list item with a real swipe-to-delete gesture - not a
 * fake CSS hover effect, an actual drag interaction using Framer
 * Motion's pan/drag gestures. Dragging left reveals a red delete
 * action behind the item; releasing past DELETE_THRESHOLD commits the
 * delete (calling onDelete), releasing short of it snaps back.
 *
 * Deliberately scoped to ONE list (CRM Leads) as the real, tested
 * integration rather than force-fitting this gesture onto every list
 * in the app - see MANUAL.md for the reasoning. Reusable as-is for any
 * other list that wants the same behavior later.
 */
export function SwipeToDelete({ children, onDelete }: { children: React.ReactNode; onDelete: () => void }) {
  const x = useMotionValue(0);
  const deleteOpacity = useTransform(x, [DELETE_THRESHOLD, 0], [1, 0]);
  const [deleting, setDeleting] = useState(false);

  function handleDragEnd() {
    if (x.get() <= DELETE_THRESHOLD) {
      setDeleting(true);
      // Animate the rest of the way off-screen before actually calling
      // onDelete, so the item visibly finishes leaving rather than
      // vanishing mid-swipe the instant the threshold is crossed.
      animate(x, -400, { duration: 0.2, onComplete: onDelete });
    } else {
      animate(x, 0, { type: "spring", stiffness: 500, damping: 30 });
    }
  }

  return (
    <div className="relative overflow-hidden rounded-lg">
      <motion.div
        // pointer-events-none is essential: this layer is absolutely positioned,
        // so it paints OVER the (non-positioned) row. Opacity 0 hides it but does
        // not stop it receiving clicks, which made every control in the row dead.
        className="pointer-events-none absolute inset-0 z-0 bg-red-600 flex items-center justify-end pr-4 rounded-lg"
        style={{ opacity: deleteOpacity }}
        aria-hidden="true"
      >
        <Trash2 className="text-white" size={18} />
      </motion.div>
      <motion.div
        drag={deleting ? false : "x"}
        dragConstraints={{ left: MAX_DRAG, right: 0 }}
        dragElastic={0.15}
        style={{ x }}
        onDragEnd={handleDragEnd}
        className="relative z-10 touch-pan-y"
      >
        {children}
      </motion.div>
    </div>
  );
}
